#include "postgres_fe.h"

#include <unistd.h>

#include "catalog/pg_tablespace_d.h"
#include "common/file_perm.h"

#include "file_ops.h"
#include "filemap.h"
#include "pg_rewind.h"
#include "tde_ops.h"

#include "access/pg_tde_tdemap.h"
#include "common/pg_tde_utils.h"
#include "pg_tde.h"

static void copy_dir(const char *src, const char *dst);

typedef struct
{
	InternalKey *source_key;
	InternalKey *target_key;
	char		path[MAXPGPATH];
	RelFileLocator rlocator;
	unsigned int segNo;
} current_file_data;

static current_file_data current_tde_file =
{
	0
};

/* Dir for an operational copy of source's tde files (_keys, etc)  */
static char tde_tmp_scource[MAXPGPATH] = "/tmp/pg_tde_rewindXXXXXX";

void
flush_current_key(void)
{
	if (current_tde_file.source_key == NULL)
		return;

	pg_log_debug("update internal key for \"%s\"", current_tde_file.path);
	pg_tde_set_data_dir(tde_tmp_scource);
	pg_tde_save_smgr_key(current_tde_file.rlocator, current_tde_file.target_key, true);

	pfree(current_tde_file.source_key);
	pfree(current_tde_file.target_key);
	memset(&current_tde_file, 0, sizeof(current_tde_file));
}

void
ensure_tde_keys(const char *relpath)
{
	char		target_tde_path[MAXPGPATH];
	RelFileLocator rlocator;
	unsigned int segNo;

	/* the same file, nothing to do */
	if (strcmp(current_tde_file.path, relpath) == 0)
		return;

	flush_current_key();

	path_rlocator(relpath, &rlocator, &segNo);

	pg_tde_set_data_dir(tde_tmp_scource);
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
encrypt_block(unsigned char *buf, off_t file_offset)
{
	BlockNumber blkno;

	/* not a tde file, nothing do to */
	if (current_tde_file.source_key == NULL)
		return;

	Assert(file_offset % BLCKSZ == 0);

	blkno = file_offset / BLCKSZ + current_tde_file.segNo * RELSEG_SIZE;

	pg_log_debug("re-encrypt block in %s, offset: %ld, blockNum: %u", current_tde_file.path, (long) file_offset, blkno);
	tde_decrypt_smgr_block(current_tde_file.source_key, MAIN_FORKNUM, blkno, buf, buf);
	tde_encrypt_smgr_block(current_tde_file.target_key, MAIN_FORKNUM, blkno, buf, buf);
}


void
create_tde_tmp_dir(void)
{
	if (mkdtemp(tde_tmp_scource) == NULL)
		pg_fatal("could not create temporary directory \"%s\": %m", tde_tmp_scource);

	atexit(destroy_tde_tmp_dir);

	pg_log_debug("created temporary pg_tde directory: %s", tde_tmp_scource);
}

void
destroy_tde_tmp_dir(void)
{
	rmtree(tde_tmp_scource, true);
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

	snprintf(path, MAXPGPATH, "%s/%s", tde_tmp_scource, fname);

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
copy_tmp_tde_files(const char *from)
{
	copy_dir(from, tde_tmp_scource);
}

void
fetch_tde_dir(void)
{
	char		target_tde_dir[MAXPGPATH];

	if (dry_run)
		return;

	snprintf(target_tde_dir, MAXPGPATH, "%s/%s", datadir_target, PG_TDE_DATA_DIR);

	rmtree(target_tde_dir, false);
	copy_dir(tde_tmp_scource, target_tde_dir);
}
