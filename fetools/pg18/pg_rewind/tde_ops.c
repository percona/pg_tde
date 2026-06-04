#include "postgres_fe.h"

#include <unistd.h>

#include "access/xlog_internal.h"
#include "catalog/pg_tablespace_d.h"
#include "common/file_perm.h"

#include "file_ops.h"
#include "filemap.h"
#include "pg_rewind.h"
#include "tde_ops.h"

#include "access/pg_tde_tdemap.h"
#include "access/pg_tde_xlog_keys.h"
#include "access/pg_tde_xlog_smgr.h"
#include "common/pg_tde_utils.h"
#include "common/hashfn.h"
#include "pg_tde.h"

static void copy_dir(const char *src, const char *dst);
static void create_tde_tmp_dir(void);

typedef struct
{
	InternalKey *source_key;
	InternalKey *target_key;
	char		path[MAXPGPATH];
	RelFileLocator rlocator;
	unsigned int segNo;
} current_file_data;

static current_file_data current_tde_file = {0};

typedef struct flushkey_entry
{
	RelFileLocator rloc;
	InternalKey *target_key;

	uint32		status;			/* used by hash table */
} flushkey_entry;

#define SH_PREFIX				flushkey
#define SH_ELEMENT_TYPE			flushkey_entry
#define SH_KEY_TYPE				RelFileLocator
#define SH_KEY					rloc
#define SH_HASH_KEY(tb, key)	hash_combine(hash_combine(hash_bytes_uint32((key).spcOid), \
											 hash_bytes_uint32((key).dbOid)), \
										 hash_bytes_uint32((key).relNumber))
#define SH_EQUAL(tb, a, b)		RelFileLocatorEquals(a, b)
#define SH_SCOPE				static inline
#define SH_RAW_ALLOCATOR		pg_malloc0
#define SH_DECLARE
#define SH_DEFINE
#include "lib/simplehash.h"

#define FLUSHKEY_INIT_SIZE 1000

static flushkey_hash *flushkey = NULL;

/* Dir for an operational copy of source's tde files (_keys, etc)  */
static char tde_tmp_source[MAXPGPATH] = "/tmp/pg_tde_rewindXXXXXX";
static bool source_has_tde = false;

static void reencrypt_fork(ForkNumber fork);

/* Initialise hashtabe for re-encryption keys */
void
tde_flushkey_init(void)
{
	flushkey = flushkey_create(FLUSHKEY_INIT_SIZE, NULL);
}

/*
 * Add used a key that was used for relation re-encrion to the hash. We will
 * write them later to the source key files at the end of rewind.
 */
static void
flushkey_add_entry(RelFileLocator rloc, InternalKey *key)
{
	flushkey_entry *entry;
	bool		found;

	Assert(key != NULL);
	Assert(flushkey != NULL);

	entry = flushkey_insert(flushkey, rloc, &found);

	if (!found)
	{
		entry->rloc = rloc;
		entry->target_key = key;

		Assert(current_tde_file.source_key != NULL);

		/* TODO: should this be moved to flush_rel_keys()? */
		reencrypt_fork(FSM_FORKNUM);
		reencrypt_fork(VISIBILITYMAP_FORKNUM);

		/* free only the source key, as we need the target's one for later */
		pfree(current_tde_file.source_key);
		memset(&current_tde_file, 0, sizeof(current_tde_file));
	}
}

/*
 * Write all destination internal key that was used to re-encrypt relation data
 * to the sorce (if there is any).
 */
void
flush_rel_keys(void)
{
	flushkey_iterator iter;
	flushkey_entry *entry;

	if (flushkey == NULL)
		return;

	/* add keys for the last file, if there are any */
	if (current_tde_file.source_key != NULL)
		flushkey_add_entry(current_tde_file.rlocator, current_tde_file.target_key);

	pg_tde_set_data_dir(tde_tmp_source);
	flushkey_start_iterate(flushkey, &iter);

	while ((entry = flushkey_iterate(flushkey, &iter)) != NULL)
	{
		RelPathStr	rp = relpathperm(entry->rloc, MAIN_FORKNUM);

		Assert(entry->target_key != NULL);

		pg_log_debug("update internal key for \"%s\"", rp.str);

		if (!dry_run)
			pg_tde_save_smgr_key(entry->rloc, entry->target_key, true);

		pfree(entry->target_key);
	}
}

static void
reencrypt_fork(ForkNumber fork)
{
	int			srcfd;
	int			trgfd;
	char		srcpath[MAXPGPATH];
	PGIOAlignedBlock buf;
	size_t		written_len;
	RelPathStr	rp = relpathperm(current_tde_file.rlocator, fork);
	static const char *const warning_hint = "Skipping the file, as the server can start and rebuild the broken VM/FSM file.";

	if (dry_run)
		return;

	snprintf(srcpath, sizeof(srcpath), "%s/%s", datadir_target, rp.str);

	/* check if fork exists, nothing to do if it does not */
	if (access(srcpath, F_OK) != 0)
		return;

	srcfd = open(srcpath, O_RDONLY | PG_BINARY, 0);
	if (srcfd < 0)
	{
		/*
		 * Server can recover from wrecked VM/FSM, hence only warnings here
		 * and in the rest of the function
		 */
		pg_log_warning("could not open fork file for reading \"%s\": %m", srcpath);
		pg_log_warning_hint("%s", warning_hint);
		return;
	}

	trgfd = open(srcpath, O_WRONLY | PG_BINARY, 0);
	if (trgfd < 0)
	{
		pg_log_warning("could not open fork file for writing \"%s\": %m", srcpath);
		pg_log_warning_hint("%s", warning_hint);
		close(srcfd);
		return;
	}

	written_len = 0;
	for (;;)
	{
		ssize_t		read_len;

		read_len = read(srcfd, buf.data, sizeof(buf.data));

		if ((read_len <= 0))
		{
			if (read_len < 0)
			{
				pg_log_warning("could not read block from fork file \"%s\": %m", srcpath);
				pg_log_warning_hint("%s", warning_hint);
			}

			break;				/* EOF reached if read_len == 0 */
		}

		if (read_len != BLCKSZ)
		{
			pg_log_warning("unexpected read from fork file \"%s\"", srcpath);
			pg_log_warning_detail("Expected %d bytes, but got %lu", BLCKSZ, read_len);
			pg_log_warning_hint("%s", warning_hint);

			break;
		}

		tde_reencrypt_block((unsigned char *) buf.data, written_len, fork);

		if (write(trgfd, buf.data, read_len) != read_len)
		{
			pg_log_warning("could not write block to fork file \"%s\": %m", srcpath);
			pg_log_warning_hint("%s", warning_hint);

			break;
		}
		written_len += read_len;
	}

	close(srcfd);
	close(trgfd);
}

void
ensure_tde_wal_seg(const char *relpath)
{
	char		target_tde_path[MAXPGPATH];
	char		wal_path[MAXPGPATH];
	PGAlignedXLogBlock buf;
	int			fd;
	ssize_t		read_len;
	off_t		offset = 0;
	XLogSegNo	segno;
	TimeLineID	tli;
	const char *segname = last_dir_separator(relpath);

	pg_log_debug("re-encrypt target WAL segment %s", relpath);

	if (dry_run)
		return;

	segname = (segname != NULL) ? segname + 1 : relpath;
	XLogFromFileName(segname, &tli, &segno, WalSegSz);

	snprintf(wal_path, sizeof(wal_path), "%s/%s", datadir_target, relpath);

	fd = open(wal_path, O_RDWR | PG_BINARY, 0);
	if (fd < 0)
	{
		/*
		 * A warning here and in further as the kept segment is not necessary
		 * encrypted with the wrong key. Hence failing here still may result
		 * in recoverable server.
		 */
		pg_log_warning("could not open WAL segment \"%s\": %m", wal_path);
		return;
	}

	snprintf(target_tde_path, sizeof(target_tde_path), "%s/%s", datadir_target, PG_TDE_DATA_DIR);

	/*
	 * XXX: Should we slurp the whole segment and don't bother with switching
	 * keys every XLOG_BLCKSZ?
	 */
	while ((read_len = pg_pread(fd, buf.data, sizeof(buf.data), offset)) > 0)
	{
		/* decrypt with target keys */
		pg_tde_set_data_dir(target_tde_path);
		TDEXLogCryptBuffer(buf.data, buf.data, read_len, offset, tli, segno, WalSegSz);

		/* reencrypt with source keys */
		pg_tde_set_data_dir(tde_tmp_source);
		TDEXLogCryptBuffer(buf.data, buf.data, read_len, offset, tli, segno, WalSegSz);

		if (pg_pwrite(fd, buf.data, read_len, offset) != read_len)
		{
			pg_log_warning("could not write WAL segment \"%s\": %m", wal_path);
			break;
		}
		offset += read_len;
	}

	close(fd);
}

void
ensure_tde_keys(const char *relpath)
{
	char		target_tde_path[MAXPGPATH];
	RelFileLocator rlocator;
	unsigned int segNo;

	/* no TDE on source, nothing to do */
	if (!source_has_tde)
		return;

	if (!path_rlocator(relpath, &rlocator, &segNo))
		return;

	/* the same relation, nothing to do */
	if (RelFileLocatorEquals(rlocator, current_tde_file.rlocator))
		return;

	if (current_tde_file.source_key != NULL)
		flushkey_add_entry(current_tde_file.rlocator, current_tde_file.target_key);

	pg_tde_set_data_dir(tde_tmp_source);
	current_tde_file.source_key = pg_tde_get_smgr_key(rlocator);

	snprintf(target_tde_path, sizeof(target_tde_path), "%s/%s", datadir_target, PG_TDE_DATA_DIR);
	pg_tde_set_data_dir(target_tde_path);
	current_tde_file.target_key = pg_tde_get_smgr_key(rlocator);

	if (current_tde_file.source_key != NULL)
	{
		/*
		 * If there ever was a source_key, it must be a target_key for this
		 * rlocator. `ALTER TABLE ... SET ACCESS METHOD heap` would create a
		 * new rlocator, hence it would not be a range chage.
		 *
		 * XXX: should be an elog FATAL instead?
		 */
		Assert(current_tde_file.target_key != NULL);

		memset(current_tde_file.path, 0, MAXPGPATH);
		strlcpy(current_tde_file.path, relpath, MAXPGPATH);
		current_tde_file.rlocator = rlocator;
		current_tde_file.segNo = segNo;
	}
}

void
tde_reencrypt_block(unsigned char *buf, off_t file_offset, ForkNumber fork)
{
	BlockNumber blkno;

	/* not a tde file, nothing do to */
	if (current_tde_file.source_key == NULL)
		return;

	Assert(file_offset % BLCKSZ == 0);

	blkno = file_offset / BLCKSZ + current_tde_file.segNo * RELSEG_SIZE;

	pg_log_debug("re-encrypt block in %s, offset: %ld, blockNum: %u", current_tde_file.path, (long) file_offset, blkno);
	tde_decrypt_smgr_block(current_tde_file.source_key, fork, blkno, buf, buf);
	tde_encrypt_smgr_block(current_tde_file.target_key, fork, blkno, buf, buf);
}

static void
create_tde_tmp_dir(void)
{
	if (mkdtemp(tde_tmp_source) == NULL)
		pg_fatal("could not create temporary directory \"%s\": %m", tde_tmp_source);

	pg_log_debug("created temporary pg_tde directory: %s", tde_tmp_source);
}

void
destroy_tde_tmp_dir(void)
{
	rmtree(tde_tmp_source, true);
}

static void
write_file(const char *path, char *buf, size_t size)
{
	int			fd;

	fd = open(path, O_WRONLY | O_CREAT | PG_BINARY, pg_file_create_mode);
	if (fd < 0)
		pg_fatal("could not create temporary tde file \"%s\": %m", path);

	if (write(fd, buf, size) != size)
		pg_fatal("could not write temporary tde file \"%s\": %m", path);

	if (close(fd) != 0)
		pg_fatal("could not close temporary tde file \"%s\": %m", path);
}

void
write_tmp_source_file(const char *fname, char *buf, size_t size)
{
	char		path[MAXPGPATH];

	snprintf(path, MAXPGPATH, "%s/%s", tde_tmp_source, fname);

	write_file(path, buf, size);
}

static void
copy_dir(const char *src, const char *dst)
{
	DIR		   *xldir;
	struct dirent *xlde;
	char		src_path[MAXPGPATH];
	char		dst_path[MAXPGPATH];

	xldir = opendir(src);
	if (xldir == NULL)
		pg_fatal("could not open directory \"%s\": %m", src);

	while (errno = 0, (xlde = readdir(xldir)) != NULL)
	{
		struct stat fst;

		if (strcmp(xlde->d_name, ".") == 0 ||
			strcmp(xlde->d_name, "..") == 0)
			continue;

		snprintf(src_path, sizeof(src_path), "%s/%s", src, xlde->d_name);
		snprintf(dst_path, sizeof(dst_path), "%s/%s", dst, xlde->d_name);

		if (lstat(src_path, &fst) < 0)
			pg_fatal("could not stat file \"%s\": %m", src_path);

		if (S_ISREG(fst.st_mode))
		{
			char	   *buf;
			size_t		size;

			buf = slurpFile(src, xlde->d_name, &size);

			write_file(dst_path, buf, size);
			pg_free(buf);
		}
	}

	if (errno)
		pg_fatal("could not read directory \"%s\": %m", src);

	if (closedir(xldir))
		pg_fatal("could not close directory \"%s\": %m", src);
}

void
init_tde(void)
{
	source_has_tde = true;
	create_tde_tmp_dir();
	atexit(destroy_tde_tmp_dir);
}

void
copy_tmp_tde_files(const char *from)
{
	copy_dir(from, tde_tmp_source);
}

void
fetch_tde_dir(void)
{
	char		target_tde_dir[MAXPGPATH];

	if (dry_run)
		return;

	if (!source_has_tde)
		return;

	snprintf(target_tde_dir, MAXPGPATH, "%s/%s", datadir_target, PG_TDE_DATA_DIR);

	rmtree(target_tde_dir, false);
	copy_dir(tde_tmp_source, target_tde_dir);
}
