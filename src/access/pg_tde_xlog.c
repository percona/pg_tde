/*-------------------------------------------------------------------------
 *
 * pg_tde_xlog.c
 *	  TDE XLog resource manager
 *
 *
 * IDENTIFICATION
 *	  src/access/pg_tde_xlog.c
 *
 *-------------------------------------------------------------------------
 */

#include "postgres.h"

#include "pg_tde_defines.h"
#include "access/xlog.h"
#include "access/xlog_internal.h"
#include "access/xloginsert.h"
#include "storage/bufmgr.h"
#include "storage/shmem.h"
#include "utils/memutils.h"

#include "access/pg_tde_tdemap.h"
#include "access/pg_tde_xlog.h"
#include "catalog/tde_master_key.h"
#include "encryption/enc_tde.h"


static char *TDEXLogEncryptBuf = NULL;

static void SetXLogPageIVPrefix(TimeLineID tli, XLogRecPtr lsn, char* iv_prefix);
static int XLOGChooseNumBuffers(void);
/*
 * TDE fork XLog
 */
void
pg_tde_rmgr_redo(XLogReaderState *record)
{
	uint8		info = XLogRecGetInfo(record) & ~XLR_INFO_MASK;

	if (info == XLOG_TDE_ADD_RELATION_KEY)
	{
		XLogRelKey *xlrec = (XLogRelKey *) XLogRecGetData(record);

		pg_tde_write_key_map_entry(&xlrec->rlocator, &xlrec->relKey, NULL);
	}
	else if (info == XLOG_TDE_ADD_MASTER_KEY)
	{
		TDEMasterKeyInfo *mkey = (TDEMasterKeyInfo *) XLogRecGetData(record);

		save_master_key_info(mkey);
	}
	else if (info == XLOG_TDE_CLEAN_MASTER_KEY)
	{
		XLogMasterKeyCleanup *xlrec = (XLogMasterKeyCleanup *) XLogRecGetData(record);

		cleanup_master_key_info(xlrec->databaseId, xlrec->tablespaceId);
	}
	else if (info == XLOG_TDE_ROTATE_KEY)
	{
		XLogMasterKeyRotate *xlrec = (XLogMasterKeyRotate *) XLogRecGetData(record);

		xl_tde_perform_rotate_key(xlrec);
	}
	else
	{
		elog(PANIC, "pg_tde_redo: unknown op code %u", info);
	}
}

void
pg_tde_rmgr_desc(StringInfo buf, XLogReaderState *record)
{
	uint8		info = XLogRecGetInfo(record) & ~XLR_INFO_MASK;

	if (info == XLOG_TDE_ADD_RELATION_KEY)
	{
		XLogRelKey *xlrec = (XLogRelKey *) XLogRecGetData(record);

		appendStringInfo(buf, "add tde internal key for relation %u/%u", xlrec->rlocator.dbOid, xlrec->rlocator.relNumber);
	}
	if (info == XLOG_TDE_ADD_MASTER_KEY)
	{
		TDEMasterKeyInfo *xlrec = (TDEMasterKeyInfo *) XLogRecGetData(record);

		appendStringInfo(buf, "add tde master key for db %u/%u", xlrec->databaseId, xlrec->tablespaceId);
	}
	if (info == XLOG_TDE_CLEAN_MASTER_KEY)
	{
		XLogMasterKeyCleanup *xlrec = (XLogMasterKeyCleanup *) XLogRecGetData(record);

		appendStringInfo(buf, "cleanup tde master key info for db %u/%u", xlrec->databaseId, xlrec->tablespaceId);
	}
	if (info == XLOG_TDE_ROTATE_KEY)
	{
		XLogMasterKeyRotate *xlrec = (XLogMasterKeyRotate *) XLogRecGetData(record);

		appendStringInfo(buf, "rotate master key for %u", xlrec->databaseId);
	}
}

const char *
pg_tde_rmgr_identify(uint8 info)
{
	if ((info & ~XLR_INFO_MASK) == XLOG_TDE_ADD_RELATION_KEY)
		return "XLOG_TDE_ADD_RELATION_KEY";

	if ((info & ~XLR_INFO_MASK) == XLOG_TDE_ADD_MASTER_KEY)
		return "XLOG_TDE_ADD_MASTER_KEY";

	if ((info & ~XLR_INFO_MASK) == XLOG_TDE_CLEAN_MASTER_KEY)
		return "XLOG_TDE_CLEAN_MASTER_KEY";

	return NULL;
}

/* 
 * XLog Storage Manager
 * TODO:
 * 	- Should be a config option "on/off"?
 *  - Currently it encrypts WAL XLog Pages, should we encrypt whole Segments? `initdb` for
 *    example generates a write of 312 pages - so 312 "gen IV" and "encrypt" runs instead of one.
 * 	  Would require though an extra read() during recovery/was_send etc to check `XLogPageHeader`
 *    if segment is encrypted.
 *    We could also encrypt Records while adding them to the XLog Buf but it'll be the slowest (?).
 */

static int
XLOGChooseNumBuffers(void)
{
	int			xbuffers;

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
TDEXLogEncryptBuffSize()
{
	int		xbuffers;

	xbuffers = (XLOGbuffers == -1) ? XLOGChooseNumBuffers() : XLOGbuffers;
	return (Size) XLOG_BLCKSZ * xbuffers;
}

/* 
 * Alloc memory for encrypition buffer.
 * 
 * It should fit XLog buffers (XLOG_BLCKSZ * wal_buffers). We can't
 * (re)alloc this buf in pg_tde_xlog_seg_write() based on the write size as
 * it's called in the CRIT section, hence no allocations are allowed.
 * 
 * Access to this buffer happens during XLogWrite() call which should
 * be called with WALWriteLock held, hence no need in extra locks.
 */
void
TDEXLogShmemInit(void)
{
	bool	foundBuf;

	TDEXLogEncryptBuf = (char *)
		TYPEALIGN(PG_IO_ALIGN_SIZE,
				  ShmemInitStruct("TDE XLog Encrypt Buffer",
								  XLOG_TDE_ENC_BUFF_ALIGNED_SIZE,
								  &foundBuf));
}

void
TDEInitXLogSmgr(void)
{
	SetXLogSmgr(&tde_xlog_smgr);
}

/* 
 * TODO: proper key management
 *		 where to store refs to the master and internal keys?
 */
static InternalKey XLogInternalKey = {.key = {0xD,}};

ssize_t
pg_tde_xlog_seg_write(int fd, const void *buf, size_t count, off_t offset)
{
	Size	page_off = 0;
	char	iv_prefix[16] = {0,};
	uint32	data_size = 0;
	XLogPageHeader	page;
	XLogPageHeader	crypt_page;
	RelKeyData		key = {.internal_key = XLogInternalKey};

	Assert((count % (Size) XLOG_BLCKSZ) == 0);

#ifdef TDE_XLOG_DEBUG
	elog(DEBUG1, "Write to a WAL segment, pages amount: %d", count / (Size) XLOG_BLCKSZ);
#endif
	/* Encrypt pages */
	for (page_off = 0; page_off < count; page_off += (Size) XLOG_BLCKSZ)
	{
		page = (XLogPageHeader) ((char *) buf + page_off);

		Assert(page->xlp_magic == XLOG_PAGE_MAGIC);

		crypt_page = (XLogPageHeader) (((char *) TDEXLogEncryptBuf) + page_off);
		memcpy(crypt_page, page, (Size) XLogPageHeaderSize(page));
		crypt_page->xlp_info |= XLP_ENCRYPTED;

		data_size = (uint32) XLOG_BLCKSZ - (uint32) XLogPageHeaderSize(crypt_page);
		SetXLogPageIVPrefix(crypt_page->xlp_tli, crypt_page->xlp_pageaddr, iv_prefix);
		PG_TDE_ENCRYPT_DATA(iv_prefix, (uint32) offset + page_off, (char *) page + XLogPageHeaderSize(page), data_size, (char *) crypt_page + (Size) XLogPageHeaderSize(crypt_page), &key);
	}

	return pg_pwrite(fd, TDEXLogEncryptBuf, count, offset);
}

ssize_t
pg_tde_xlog_seg_read(int fd, void *buf, size_t count, off_t offset)
{
	ssize_t readsz;
	Size	page_off;
	char	iv_prefix[16] = {0,};
	uint32	data_size = 0;
	XLogPageHeader	page;
	RelKeyData		key = {.internal_key = XLogInternalKey};
	char	*decrypt_buf = NULL;

#ifdef TDE_XLOG_DEBUG
	elog(DEBUG1, "Read from a WAL segment, pages amount: %d", count / (Size) XLOG_BLCKSZ);
#endif

	readsz = pg_pread(fd, buf, count, offset);

	for (page_off = 0; page_off < count; page_off += (Size) XLOG_BLCKSZ)
	{
		page = (XLogPageHeader) ((char *) buf + page_off);

		Assert(page->xlp_magic == XLOG_PAGE_MAGIC);

		if (page->xlp_info & XLP_ENCRYPTED)
		{
			if (decrypt_buf == NULL) {
				decrypt_buf = (char *) palloc(XLOG_BLCKSZ - SizeOfXLogShortPHD);
			}
			data_size = (uint32) XLOG_BLCKSZ - (uint32) XLogPageHeaderSize(page);
			SetXLogPageIVPrefix(page->xlp_tli, page->xlp_pageaddr, iv_prefix);
			PG_TDE_DECRYPT_DATA(iv_prefix, (uint32) offset + page_off, (char *) page + XLogPageHeaderSize(page), data_size, decrypt_buf, &key);

			memcpy((char *) page + XLogPageHeaderSize(page), decrypt_buf, data_size);
		}
	}
	
	if (decrypt_buf != NULL) {
		pfree(decrypt_buf);
	}

	return readsz;
}

/* IV: TLI(uint32) + XLogRecPtr(uint64)*/
static void
SetXLogPageIVPrefix(TimeLineID tli, XLogRecPtr lsn, char* iv_prefix)
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