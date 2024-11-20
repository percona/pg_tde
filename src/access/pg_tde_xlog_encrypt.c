/*-------------------------------------------------------------------------
 *
 * pg_tde_xlog_encrypt.c
 *	  Encrypted XLog storage manager
 *
 *
 * IDENTIFICATION
 *	  src/access/pg_tde_xlog_encrypt.c
 *
 *-------------------------------------------------------------------------
 */

#include "postgres.h"

#ifdef PERCONA_EXT
#include "pg_tde.h"
#include "pg_tde_defines.h"
#include "access/xlog.h"
#include "access/xlog_internal.h"
#include "access/xloginsert.h"
#include "storage/bufmgr.h"
#include "storage/shmem.h"
#include "utils/guc.h"
#include "utils/memutils.h"

#include "access/pg_tde_xlog_encrypt.h"
#include "catalog/tde_global_space.h"
#include "encryption/enc_tde.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

static XLogPageHeaderData DecryptCurrentPageHrd;

static void SetXLogPageIVPrefix(TimeLineID tli, XLogRecPtr lsn, char *iv_prefix);

#ifndef FRONTEND
/* GUC */
static bool EncryptXLog = false;

static XLogPageHeaderData EncryptCurrentPageHrd;

static ssize_t TDEXLogWriteEncryptedPages(int fd, const void *buf, size_t count, off_t offset);
static char *TDEXLogEncryptBuf = NULL;
static int XLOGChooseNumBuffers(void);

void
XLogInitGUC(void)
{
	DefineCustomBoolVariable("pg_tde.wal_encrypt",	/* name */
							 "Enable/Disable encryption of WAL.",	/* short_desc */
							 NULL,	/* long_desc */
							 &EncryptXLog,	/* value address */
							 false, /* boot value */
							 PGC_POSTMASTER,	/* context */
							 0, /* flags */
							 NULL,	/* check_hook */
							 NULL,	/* assign_hook */
							 NULL	/* show_hook */
		);
}

static int
XLOGChooseNumBuffers(void)
{
	int xbuffers;

	xbuffers = NBuffers / 32;
	if (xbuffers > (wal_segment_size / XLOG_BLCKSZ))
		xbuffers = (wal_segment_size / XLOG_BLCKSZ);
	if (xbuffers < 8)
		xbuffers = 8;
	return xbuffers;
}

/*
 * Defines the size of the XLog encryption buffer
 */
Size
TDEXLogEncryptBuffSize(void)
{
	int xbuffers;

	xbuffers = (XLOGbuffers == -1) ? XLOGChooseNumBuffers() : XLOGbuffers;
	return (Size) XLOG_BLCKSZ * xbuffers;
}

/*
 * Alloc memory for the encryption buffer.
 *
 * It should fit XLog buffers (XLOG_BLCKSZ * wal_buffers). We can't
 * (re)alloc this buf in tdeheap_xlog_seg_write() based on the write size as
 * it's called in the CRIT section, hence no allocations are allowed.
 *
 * Access to this buffer happens during XLogWrite() call which should
 * be called with WALWriteLock held, hence no need in extra locks.
 */
void
TDEXLogShmemInit(void)
{
	bool foundBuf;

	if (EncryptXLog)
	{
		TDEXLogEncryptBuf = (char *)
			TYPEALIGN(PG_IO_ALIGN_SIZE,
					  ShmemInitStruct("TDE XLog Encryption Buffer",
									  XLOG_TDE_ENC_BUFF_ALIGNED_SIZE,
									  &foundBuf));

		elog(DEBUG1, "pg_tde: initialized encryption buffer %lu bytes", XLOG_TDE_ENC_BUFF_ALIGNED_SIZE);
	}
}

/*
 * Encrypt XLog page(s) from the buf and write to the segment file.
 */
static ssize_t
TDEXLogWriteEncryptedPages(int fd, const void *buf, size_t count, off_t offset)
{
	char iv_prefix[16] = {0,};
	size_t data_size = 0;
	XLogPageHeader curr_page_hdr = &EncryptCurrentPageHrd;
	XLogPageHeader enc_buf_page;
	RelKeyData *key = GetTdeGlobaleRelationKey(GLOBAL_SPACE_RLOCATOR(XLOG_TDE_OID));
	off_t enc_off;
	size_t page_size = XLOG_BLCKSZ - offset % XLOG_BLCKSZ;
	uint32 iv_ctr = 0;

#ifdef TDE_XLOG_DEBUG
	elog(DEBUG1, "write encrypted WAL, pages amount: %d, size: %lu offset: %ld", count / (Size) XLOG_BLCKSZ, count, offset);
#endif

	/*
	 * Go through the buf page-by-page and encrypt them. We may start or
	 * finish writing from/in the middle of the page (walsender or
	 * `full_page_writes = off`). So preserve a page header for the IV init
	 * data.
	 *
	 * TODO: check if walsender restarts form the beggining of the page in
	 * case of the crash.
	 */
	for (enc_off = 0; enc_off < count;)
	{
		data_size = Min(page_size, count);

		if (page_size == XLOG_BLCKSZ)
		{
			memcpy((char *) curr_page_hdr, (char *) buf + enc_off, SizeOfXLogShortPHD);

			/*
			 * Need to use a separate buf for the encryption so the page
			 * remains non-crypted in the XLog buf (XLogInsert has to have
			 * access to records' lsn).
			 */
			enc_buf_page = (XLogPageHeader) (TDEXLogEncryptBuf + enc_off);
			memcpy((char *) enc_buf_page, (char *) buf + enc_off, (Size) XLogPageHeaderSize(curr_page_hdr));
			enc_buf_page->xlp_info |= XLP_ENCRYPTED;

			enc_off += XLogPageHeaderSize(curr_page_hdr);
			data_size -= XLogPageHeaderSize(curr_page_hdr);
			/* it's a beginning of the page */
			iv_ctr = 0;
		}
		else
		{
			/* we're in the middle of the page */
			iv_ctr = (offset % XLOG_BLCKSZ) - XLogPageHeaderSize(curr_page_hdr);
		}

		if (data_size + enc_off > count)
		{
			data_size = count - enc_off;
		}

		/*
		 * The page is zeroed (no data), no sense to enctypt. This may happen
		 * when base_backup or other requests XLOG SWITCH and some pages in
		 * XLog buffer still not used.
		 */
		if (curr_page_hdr->xlp_magic == 0)
		{
			/* ensure all the page is {0} */
			Assert((*((char *) buf + enc_off) == 0) &&
				   memcmp((char *) buf + enc_off, (char *) buf + enc_off + 1, data_size - 1) == 0);

			memcpy((char *) enc_buf_page, (char *) buf + enc_off, data_size);
		}
		else
		{
			SetXLogPageIVPrefix(curr_page_hdr->xlp_tli, curr_page_hdr->xlp_pageaddr, iv_prefix);
			PG_TDE_ENCRYPT_DATA(iv_prefix, iv_ctr, (char *) buf + enc_off, data_size,
								TDEXLogEncryptBuf + enc_off, key);
		}

		page_size = XLOG_BLCKSZ;
		enc_off += data_size;
	}

	return pg_pwrite(fd, TDEXLogEncryptBuf, count, offset);
}
#endif							/* !FRONTEND */

void
TDEXLogSmgrInit(void)
{
	SetXLogSmgr(&tde_xlog_smgr);
}

ssize_t
tdeheap_xlog_seg_write(int fd, const void *buf, size_t count, off_t offset)
{
#ifndef FRONTEND
	if (EncryptXLog)
		return TDEXLogWriteEncryptedPages(fd, buf, count, offset);
	else
#endif
		return pg_pwrite(fd, buf, count, offset);
}

/*
 * Read the XLog pages from the segment file and dectypt if need.
 */
ssize_t
tdeheap_xlog_seg_read(int fd, void *buf, size_t count, off_t offset)
{
	ssize_t readsz;
	char iv_prefix[16] = {0,};
	size_t data_size = 0;
	XLogPageHeader curr_page_hdr = &DecryptCurrentPageHrd;
	RelKeyData *key = GetTdeGlobaleRelationKey(GLOBAL_SPACE_RLOCATOR(XLOG_TDE_OID));
	size_t page_size = XLOG_BLCKSZ - offset % XLOG_BLCKSZ;
	off_t dec_off;
	uint32 iv_ctr = 0;

#ifdef TDE_XLOG_DEBUG
	elog(DEBUG1, "read from a WAL segment, pages amount: %d, size: %lu offset: %ld", count / (Size) XLOG_BLCKSZ, count, offset);
#endif

	readsz = pg_pread(fd, buf, count, offset);

	/*
	 * Read the buf page by page and decypt ecnrypted pages. We may start or
	 * fihish reading from/in the middle of the page (walreceiver) in such a
	 * case we should preserve the last read page header for the IV data and
	 * the encryption state.
	 *
	 * TODO: check if walsender/receiver restarts form the beggining of the
	 * page in case of the crash.
	 */
	for (dec_off = 0; dec_off < readsz;)
	{
		data_size = Min(page_size, readsz);

		if (page_size == XLOG_BLCKSZ)
		{
			memcpy((char *) curr_page_hdr, (char *) buf + dec_off, SizeOfXLogShortPHD);

			/* set the flag to "not encrypted" for the walreceiver */
			((XLogPageHeader) ((char *) buf + dec_off))->xlp_info &= ~XLP_ENCRYPTED;

			Assert(curr_page_hdr->xlp_magic == XLOG_PAGE_MAGIC || curr_page_hdr->xlp_magic == 0);
			dec_off += XLogPageHeaderSize(curr_page_hdr);
			data_size -= XLogPageHeaderSize(curr_page_hdr);
			/* it's a beginning of the page */
			iv_ctr = 0;
		}
		else
		{
			/* we're in the middle of the page */
			iv_ctr = (offset % XLOG_BLCKSZ) - XLogPageHeaderSize(curr_page_hdr);
		}

		if ((data_size + dec_off) > readsz)
		{
			data_size = readsz - dec_off;
		}

		if (curr_page_hdr->xlp_info & XLP_ENCRYPTED)
		{
			SetXLogPageIVPrefix(curr_page_hdr->xlp_tli, curr_page_hdr->xlp_pageaddr, iv_prefix);
			PG_TDE_DECRYPT_DATA(
								iv_prefix, iv_ctr,
								(char *) buf + dec_off, data_size, (char *) buf + dec_off, key);
		}

		page_size = XLOG_BLCKSZ;
		dec_off += data_size;
	}

	return readsz;
}

/* IV: TLI(uint32) + XLogRecPtr(uint64)*/
static void
SetXLogPageIVPrefix(TimeLineID tli, XLogRecPtr lsn, char *iv_prefix)
{
	iv_prefix[0] = (tli >> 24);
	iv_prefix[1] = ((tli >> 16) & 0xFF);
	iv_prefix[2] = ((tli >> 8) & 0xFF);
	iv_prefix[3] = (tli & 0xFF);

	iv_prefix[4] = (lsn >> 56);
	iv_prefix[5] = ((lsn >> 48) & 0xFF);
	iv_prefix[6] = ((lsn >> 40) & 0xFF);
	iv_prefix[7] = ((lsn >> 32) & 0xFF);
	iv_prefix[8] = ((lsn >> 24) & 0xFF);
	iv_prefix[9] = ((lsn >> 16) & 0xFF);
	iv_prefix[10] = ((lsn >> 8) & 0xFF);
	iv_prefix[11] = (lsn & 0xFF);
}

#endif /* PERCONA_EXT */
