/*-------------------------------------------------------------------------
 *
 * local_source.c
 *	  Functions for using a local data directory as the source.
 *
 * Portions Copyright (c) 2013-2025, PostgreSQL Global Development Group
 *
 *-------------------------------------------------------------------------
 */
#include "postgres_fe.h"

#include <fcntl.h>
#include <unistd.h>

#include "catalog/pg_tablespace_d.h"
#include "common/logging.h"
#include "file_ops.h"
#include "pg_rewind.h"
#include "rewind_source.h"

#include "pg_tde.h"
#include "common/pg_tde_utils.h"
#include "access/pg_tde_tdemap.h"

typedef struct
{
	rewind_source common;		/* common interface functions */

	const char *datadir;		/* path to the source data directory */
} local_source;

static void local_traverse_files(rewind_source *source,
								 process_file_callback_t callback);
static char *local_fetch_file(rewind_source *source, const char *path,
							  size_t *filesize);
static void local_queue_fetch_file(rewind_source *source, const char *path,
								   size_t len);
static void local_queue_fetch_range(rewind_source *source, const char *path,
									off_t off, size_t len);
static void local_finish_fetch(rewind_source *source);
static void local_destroy(rewind_source *source);

rewind_source *
init_local_source(const char *datadir)
{
	local_source *src;

	src = pg_malloc0(sizeof(local_source));

	src->common.traverse_files = local_traverse_files;
	src->common.fetch_file = local_fetch_file;
	src->common.queue_fetch_file = local_queue_fetch_file;
	src->common.queue_fetch_range = local_queue_fetch_range;
	src->common.finish_fetch = local_finish_fetch;
	src->common.get_current_wal_insert_lsn = NULL;
	src->common.destroy = local_destroy;

	src->datadir = datadir;

	return &src->common;
}

static void
local_traverse_files(rewind_source *source, process_file_callback_t callback)
{
	traverse_datadir(((local_source *) source)->datadir, callback);
}

static char *
local_fetch_file(rewind_source *source, const char *path, size_t *filesize)
{
	return slurpFile(((local_source *) source)->datadir, path, filesize);
}

/*
 * Copy a file from source to target.
 *
 * 'len' is the expected length of the file.
 */
static void
local_queue_fetch_file(rewind_source *source, const char *path, size_t len)
{
	const char *datadir = ((local_source *) source)->datadir;
	PGIOAlignedBlock buf;
	char		srcpath[MAXPGPATH];
	int			srcfd;
	size_t		written_len;
	InternalKey *target_key = NULL;
	InternalKey *source_key = NULL;
	RelFileLocator rlocator;
	int 		segNo;
	char		target_tde_path[MAXPGPATH];
	char		source_tde_path[MAXPGPATH];

	snprintf(srcpath, sizeof(srcpath), "%s/%s", datadir, path);

	/* Open source file for reading */
	srcfd = open(srcpath, O_RDONLY | PG_BINARY, 0);
	if (srcfd < 0)
		pg_fatal("could not open source file \"%s\": %m",
				 srcpath);

	/* Truncate and open the target file for writing */
	open_target_file(path, true);

	/*
	 * Get keys for the relation. A NULL key means the data should not be
	 * decrypted or encrypted. Unlike fetch_range, files here might be
	 * non-relations, hence don't have rlocator at all.
	 */
	if (path_rlocator(path, &rlocator, &segNo))
	{
		snprintf(source_tde_path, sizeof(source_tde_path), "%s/%s", datadir, PG_TDE_DATA_DIR);
		pg_tde_set_data_dir(source_tde_path);
		source_key = pg_tde_get_smgr_key(rlocator);

		snprintf(target_tde_path, sizeof(target_tde_path), "%s/%s", datadir_target, PG_TDE_DATA_DIR);
		pg_tde_set_data_dir(target_tde_path);
		target_key = pg_tde_get_smgr_key(rlocator);
	}

	written_len = 0;
	for (;;)
	{
		ssize_t		read_len;

		read_len = read(srcfd, buf.data, sizeof(buf));

		if (read_len < 0)
			pg_fatal("could not read file \"%s\": %m", srcpath);
		else if (read_len == 0)
			break;				/* EOF reached */

		/*
		 * Re-encrypt blocks with a proper key if neeed.
		 * XXX: Should we encrypt the file if there is a target_key but no 
		 * source_key? If we're bringing target to the exact source's state, 
		 * then we probably should not.
		 */
		if (source_key != NULL)
		{
			BlockNumber blkno = written_len / BLCKSZ + segNo * RELSEG_SIZE;

			Assert(written_len % BLCKSZ == 0);

			pg_log_debug("__DECRYPT: %s, off: %lu, sz: %lu, forknum: %lu blockNum: %lu | KEY_SZ: %d / OID: %u", path, written_len, read_len, MAIN_FORKNUM, blkno, source_key->key_len, rlocator.relNumber);
			tde_decrypt_smgr_block(source_key, MAIN_FORKNUM, blkno, (unsigned char *) buf.data, (unsigned char *) buf.data);

			/* 
			 * If the source key exists but there is no target one, that means 
			 * VACUUM FULL moved the data to new rlocator. So create a new
			 * target key and encrypt data with it.
			 */
			if (target_key == NULL)
			{
				InternalKey key;

				pg_tde_generate_internal_key(&key, source_key->key_len);
				pg_tde_save_smgr_key(rlocator, &key, false);

				target_key = &key;
			}
		}
		if (target_key != NULL)
		{
			BlockNumber blkno = written_len / BLCKSZ + segNo * RELSEG_SIZE;

			Assert(written_len % BLCKSZ == 0);

			pg_log_debug("++EnCRYPT: %s, off: %lu, sz: %lu, forknum: %lu blockNum: %lu | KEY_SZ: %d / OID: %u", path, written_len, read_len, MAIN_FORKNUM, blkno, source_key->key_len, rlocator.relNumber);
			tde_encrypt_smgr_block(target_key, MAIN_FORKNUM, blkno, (unsigned char *) buf.data, (unsigned char *) buf.data);
		}

		write_target_range(buf.data, written_len, read_len);
		written_len += read_len;
	}

	/*
	 * A local source is not expected to change while we're rewinding, so
	 * check that the size of the file matches our earlier expectation.
	 */
	if (written_len != len)
		pg_fatal("size of source file \"%s\" changed concurrently: %d bytes expected, %d copied",
				 srcpath, (int) len, (int) written_len);

	if (close(srcfd) != 0)
		pg_fatal("could not close file \"%s\": %m", srcpath);
}

/*
 * Copy a file from source to target, starting at 'off', for 'len' bytes.
 */
static void
local_queue_fetch_range(rewind_source *source, const char *path, off_t off,
						size_t len)
{
	const char *datadir = ((local_source *) source)->datadir;
	PGIOAlignedBlock buf;
	char		srcpath[MAXPGPATH];
	int			srcfd;
	off_t		begin = off;
	off_t		end = off + len;
	InternalKey *target_key = NULL;
	InternalKey *source_key = NULL;
	RelFileLocator rlocator;
	int 		segNo;
	char		target_tde_path[MAXPGPATH];
	char		source_tde_path[MAXPGPATH];

	snprintf(srcpath, sizeof(srcpath), "%s/%s", datadir, path);

	srcfd = open(srcpath, O_RDONLY | PG_BINARY, 0);
	if (srcfd < 0)
		pg_fatal("could not open source file \"%s\": %m",
				 srcpath);

	if (lseek(srcfd, begin, SEEK_SET) == -1)
		pg_fatal("could not seek in source file: %m");

	open_target_file(path, false);

	/*
	 * Get keys for the relation. A NULL key means the data should not be
	 * decrypted or encrypted
	 */
	path_rlocator(path, &rlocator, &segNo);

	snprintf(source_tde_path, sizeof(source_tde_path), "%s/%s", datadir, PG_TDE_DATA_DIR);
	pg_tde_set_data_dir(source_tde_path);
	source_key = pg_tde_get_smgr_key(rlocator);

	snprintf(target_tde_path, sizeof(target_tde_path), "%s/%s", datadir_target, PG_TDE_DATA_DIR);
	pg_tde_set_data_dir(target_tde_path);
	target_key = pg_tde_get_smgr_key(rlocator);

	while (end - begin > 0)
	{
		ssize_t		readlen;
		size_t		thislen;

		if (end - begin > sizeof(buf))
			thislen = sizeof(buf);
		else
			thislen = end - begin;

		readlen = read(srcfd, buf.data, thislen);

		if (readlen < 0)
			pg_fatal("could not read file \"%s\": %m", srcpath);
		else if (readlen == 0)
			pg_fatal("unexpected EOF while reading file \"%s\"", srcpath);

		/* Re-encrypt blocks with a proper key if neeed. */
		if (source_key != NULL)
		{
			BlockNumber blkno = begin / BLCKSZ + segNo * RELSEG_SIZE;
			
			Assert(begin % BLCKSZ == 0);

			pg_log_debug("__DECRYPT: %s, off: %lu, sz: %lu, forknum: %lu blockNum: %lu | KEY_SZ: %d", path, begin, thislen, MAIN_FORKNUM, begin / BLCKSZ, source_key->key_len);
			tde_decrypt_smgr_block(source_key, MAIN_FORKNUM, blkno, (unsigned char *) buf.data, (unsigned char *) buf.data);

			Assert(target_key);
		}
		if (target_key != NULL)
		{
			BlockNumber blkno = begin / BLCKSZ + segNo * RELSEG_SIZE;

			Assert(begin % BLCKSZ == 0);

			pg_log_debug("++EnCRYPT: %s, off: %lu, sz: %lu, forknum: %lu blockNum: %lu | KEY_SZ: %d", path, begin, readlen, MAIN_FORKNUM, begin / BLCKSZ, source_key->key_len);
			tde_encrypt_smgr_block(target_key, MAIN_FORKNUM, blkno, (unsigned char *) buf.data, (unsigned char *) buf.data);
		}
		
		write_target_range(buf.data, begin, readlen);
		begin += readlen;
	}

	if (close(srcfd) != 0)
		pg_fatal("could not close file \"%s\": %m", srcpath);
}

static void
local_finish_fetch(rewind_source *source)
{
	/*
	 * Nothing to do, local_queue_fetch_range() copies the ranges immediately.
	 */
}

static void
local_destroy(rewind_source *source)
{
	pfree(source);
}
