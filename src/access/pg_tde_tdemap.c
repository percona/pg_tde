#include "postgres.h"

#include <openssl/err.h>
#include <openssl/rand.h>
#include <unistd.h>

#include "access/xloginsert.h"
#include "storage/fd.h"

#include "access/pg_tde_tdemap.h"
#include "access/pg_tde_xlog.h"
#include "catalog/tde_global_space.h"
#include "catalog/tde_principal_key.h"
#include "common/file_perm.h"
#include "common/pg_tde_utils.h"
#include "encryption/enc_aes.h"
#include "encryption/enc_tde.h"
#include "pg_tde.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#else
#include "access/xact.h"
#include "access/xlog.h"
#include "miscadmin.h"
#include "storage/proc.h"
#endif

/* A useful macro when debugging key encryption/decryption */
#ifdef DEBUG
#define ELOG_KEY(_msg, _key)												\
{																			\
	int i;																	\
	char buf[1024];															\
	for (i = 0; i < sizeof(_key.key); i++)					\
		sprintf(buf+i, "%02X", _key.key[i]);				\
	buf[i] = '\0';															\
	elog(INFO, "[%s] INTERNAL KEY => %s", _msg, buf);						\
}
#endif

#define PG_TDE_PRINCIPAL_KEY_FILE	"pkey_info"
#define PG_TDE_KEY_FILE_SUFFIX		"_key"
#define PG_TDE_KEY_FILENAME			"%u_%u" PG_TDE_KEY_FILE_SUFFIX

#define PG_TDE_DB_DIR_ROTATE_SUFFIX	".rotate"
#define PG_TDE_DB_DIR_OLD_SUFFIX	".old"
#define PG_TDE_DB_DIR_DELETE_SUFFIX	".rm"

/* Principal key file on disk */
typedef struct TDEFileHeader
{
	int32		file_version;
	TDESignedPrincipalKeyInfo signed_key_info;
} TDEFileHeader;

/* SMGR key on disk */
typedef struct TDESmgrKeyEntry
{
	int32		file_version;
	uint32		cipher;			/* Part of AAD. Cipher type. We support only
								 * AES_128 and AES_256 for now. */

	/*
	 * IV and tag used when encrypting the key itself
	 *
	 * TODO: should we extend MAP_ENTRY_IV_SIZE to 192(?) bit and add an
	 * iv_size filed?
	 */
	unsigned char entry_iv[MAP_ENTRY_IV_SIZE];
	unsigned char aead_tag[MAP_ENTRY_AEAD_TAG_SIZE];

	uint8		key_base_iv[INTERNAL_KEY_IV_LEN];
	uint8		encrypted_key_data[INTERNAL_KEY_MAX_LEN];
	// uint8		encrypted_key_data[FLEXIBLE_ARRAY_MEMBER]; // TODO
} TDESmgrKeyEntry;

typedef struct TDESmgrKeyAAD
{
	uint32		cipher;
	Oid			spcOid;
	RelFileNumber relNumber;
} TDESmgrKeyAAD;

static void pg_tde_set_db_dir_path(Oid dbOid, const char *suffix, char *path);
static void pg_tde_set_key_file_path(RelFileLocator rel, char *path);
static void pg_tde_set_pkey_file_path(Oid dbOid, char *path);
static TDESignedPrincipalKeyInfo *pg_tde_read_principal_key_file(const char *path);
static bool pg_tde_read_key_entry(const RelFileLocator *rlocator, TDESmgrKeyEntry *key_entry);
static void pg_tde_read_key_file(const char *file_path, TDESmgrKeyEntry *key_entry);
static InternalKey *tde_decrypt_rel_key(const TDEPrincipalKey *principal_key, TDESmgrKeyEntry *key_entry, const RelFileLocator *rlocator);
static void pg_tde_set_key_aad(TDESmgrKeyAAD *aad, uint32 cipher, const RelFileLocator *rlocator);
static void pg_tde_initialize_key_entry(TDESmgrKeyEntry *key_entry, const TDEPrincipalKey *principal_key, const RelFileLocator *rlocator, const InternalKey *rel_key_data);
static void pg_tde_write_file(const char *path, const void *data, size_t len);
static void pg_tde_durable_write_file(const char *path, const void *data, size_t len);
#ifndef FRONTEND
static void pg_tde_save_signed_principal_key(const TDESignedPrincipalKeyInfo *signed_key_info);
static void pg_tde_rotate_rel_key(const char *old_path, const char *new_path, const RelFileLocator *rlocator, const TDEPrincipalKey *old_principal_key, const TDEPrincipalKey *new_principal_key);
static bool pg_tde_parse_key_file_name(const char *name, Oid *spcOid, RelFileNumber *relNumber);
static List *pg_tde_list_key_files(Oid dbOid, Oid spcOid);
static void pg_tde_remove_dir_if_exists(const char *path);
static bool pg_tde_is_current_principal_key(Oid dbOid, const TDEPrincipalKey *principal_key);
#endif

static void
pg_tde_set_db_dir_path(Oid dbOid, const char *suffix, char *path)
{
	snprintf(path, MAXPGPATH, "%s/%u%s", pg_tde_get_data_dir(), dbOid, suffix);
}

static void
pg_tde_set_key_file_path(RelFileLocator rel, char *path)
{
	snprintf(path, MAXPGPATH, "%s/%u/" PG_TDE_KEY_FILENAME,
			 pg_tde_get_data_dir(), rel.dbOid, rel.spcOid, rel.relNumber);
}

static void
pg_tde_set_pkey_file_path(Oid dbOid, char *path)
{
	snprintf(path, MAXPGPATH, "%s/%u/" PG_TDE_PRINCIPAL_KEY_FILE,
			 pg_tde_get_data_dir(), dbOid);
}

static void
pg_tde_write_file(const char *path, const void *data, size_t len)
{
	int			fd;

	fd = OpenTransientFile(path, O_RDWR | O_CREAT | O_TRUNC | PG_BINARY);

	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not create tde file \"%s\": %m", path));
	}

	if (pg_pwrite(fd, data, len, 0) != len)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not write tde file \"%s\": %m", path));
	}

	if (pg_fsync(fd) != 0)
	{
		ereport(data_sync_elevel(ERROR),
				errcode_for_file_access(),
				errmsg("could not fsync tde file \"%s\": %m", path));
	}

	CloseTransientFile(fd);
}

/*
 * Atomically writes or replaces the file by writing a temporary one and
 * renaming it.
 */
static void
pg_tde_durable_write_file(const char *path, const void *data, size_t len)
{
	char		path_tmp[MAXPGPATH];

	snprintf(path_tmp, MAXPGPATH, "%s.r", path);

	pg_tde_write_file(path_tmp, data, len);

	durable_rename(path_tmp, path, ERROR);
}

/*
 * Saves an internal key for the given relation. If replace_existing is false,
 * the function will not overwrite an existing key for the relation, but will
 * instead do nothing.
 */
void
pg_tde_save_smgr_key(RelFileLocator rel,
					 const InternalKey *rel_key_data,
					 bool replace_existing)
{
	char		file_path[MAXPGPATH];
	LWLock	   *lock_pk = tde_lwlock_enc_keys();
	TDEPrincipalKey *principal_key;
	TDESmgrKeyEntry entry = {0};

	pg_tde_set_key_file_path(rel, file_path);

	LWLockAcquire(lock_pk, LW_EXCLUSIVE);

	if (!replace_existing && access(file_path, F_OK) == 0)
	{
		LWLockRelease(lock_pk);
		return;
	}

	principal_key = GetPrincipalKey(rel.dbOid, LW_EXCLUSIVE);
	if (principal_key == NULL)
	{
		ereport(ERROR,
				errmsg("principal key not configured"),
				errhint("Use pg_tde_set_key_using_database_key_provider() or pg_tde_set_key_using_global_key_provider() to configure one."));
	}

	pg_tde_initialize_key_entry(&entry, principal_key, &rel, rel_key_data);

#ifdef FRONTEND
	pfree(principal_key);
#endif

#ifdef USE_ASSERT_CHECKING
	{
		char		db_dir[MAXPGPATH];

		/* Should have been created along with the principal key file */
		pg_tde_set_db_dir_path(rel.dbOid, "", db_dir);
		Assert(access(db_dir, F_OK) == 0);
	}
#endif

	pg_tde_durable_write_file(file_path, &entry, sizeof(TDESmgrKeyEntry));

	LWLockRelease(lock_pk);
}

#ifndef FRONTEND
const char *
tde_sprint_key(InternalKey *k)
{
	static char buf[256];
	int			i;

	for (i = 0; i < sizeof(k->key); i++)
		sprintf(buf + i, "%02X", k->key[i]);

	return buf;
}

static void
pg_tde_save_signed_principal_key(const TDESignedPrincipalKeyInfo *signed_key_info)
{
	char		pkey_path[MAXPGPATH];
	char		dir_path[MAXPGPATH];
	TDEFileHeader fheader;

	fheader.file_version = PG_TDE_SMGR_FILE_MAGIC;
	fheader.signed_key_info = *signed_key_info;

	pg_tde_set_pkey_file_path(signed_key_info->data.databaseId, pkey_path);
	pg_tde_set_db_dir_path(signed_key_info->data.databaseId, "", dir_path);

	if (MakePGDirectory(dir_path) != 0 && errno != EEXIST)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not create tde directory \"%s\": %m", dir_path));
	}

	fsync_fname(dir_path, true);
	fsync_fname(pg_tde_get_data_dir(), true);

	pg_tde_durable_write_file(pkey_path, &fheader, sizeof(TDEFileHeader));
}

/*
 * Removes the directory with all its content if it exists.
 */
static void
pg_tde_remove_dir_if_exists(const char *path)
{
	if (access(path, F_OK) != 0)
	{
		if (errno == ENOENT)
			return;

		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not access tde directory \"%s\": %m", path));
	}

	if (!rmtree(path, true))
		ereport(ERROR,
				errmsg("could not remove tde directory \"%s\"", path));
}

/*
 * Deletes the key files for a given database.
 *
 * The directory is renamed first so the deletion is atomic. If we fail to
 * remove the renamed directory, it is removed on the next deletion of a
 * database with the same oid.
 */
void
pg_tde_delete_tde_files(Oid dbOid)
{
	char		db_dir[MAXPGPATH];
	char		rm_dir[MAXPGPATH];
	char		path[MAXPGPATH];

	pg_tde_set_db_dir_path(dbOid, "", db_dir);
	pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_DELETE_SUFFIX, rm_dir);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);

	/*
	 * Remove the leftovers of a rotation, if any. Otherwise, a stale rotate
	 * directory would be renamed to the database directory on the next start,
	 * bringing the keys back.
	 */
	pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_ROTATE_SUFFIX, path);
	pg_tde_remove_dir_if_exists(path);
	pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_OLD_SUFFIX, path);
	pg_tde_remove_dir_if_exists(path);

	/*
	 * Clean up a leftover of a previous deletion that failed with an error,
	 * if any. We proceed with the rename attempt even if rm_dir existed as
	 * there is a possibility that both db_dir and rm_dir exist (crash before
	 * fsync).
	 */
	pg_tde_remove_dir_if_exists(rm_dir);

	if (rename(db_dir, rm_dir) < 0)
	{
		if (errno != ENOENT)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("delete tde directory: could not rename \"%s\" to \"%s\": %m",
						   db_dir, rm_dir));
	}
	else
	{
		fsync_fname(pg_tde_get_data_dir(), true);
		pg_tde_remove_dir_if_exists(rm_dir);
	}

	LWLockRelease(tde_lwlock_enc_keys());
}

/*
 * Checks if the database already uses the given principal key. Creation time
 * is ignored as it differs when the rotation is replayed from WAL.
 */
static bool
pg_tde_is_current_principal_key(Oid dbOid, const TDEPrincipalKey *principal_key)
{
	TDESignedPrincipalKeyInfo *current;
	bool		result;

	current = pg_tde_get_principal_key_info(dbOid);
	if (current == NULL)
		return false;

	result = current->data.databaseId == principal_key->keyInfo.databaseId &&
		current->data.keyringId == principal_key->keyInfo.keyringId &&
		strncmp(current->data.name, principal_key->keyInfo.name, PRINCIPAL_KEY_NAME_LEN) == 0;

	pfree(current);

	return result;
}

/*
 * Finishes principal key rotations that crashed between the two renames in
 * pg_tde_perform_rotate_key(). It leaves the complete new key directory under
 * the rotate name, the previous one under the old name and no database
 * directory, so we just rename the new one back. Must be done before the WAL
 * replay, as redo needs the keys.
 *
 * We require the old directory to exist, so a rotate directory that wasn't
 * part of an interrupted swap (hence may be incomplete) is never promoted.
 *
 * Other leftovers are removed by the next rotation or deletion.
 *
 * Should be called on server start.
 */
void
pg_tde_ensure_key_dirs_on_start(void)
{
	const char *data_dir = pg_tde_get_data_dir();
	DIR		   *dir;
	struct dirent *de;
	List	   *rotate_dirs = NIL;

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);

	dir = AllocateDir(data_dir);
	if (dir == NULL)
	{
		if (errno != ENOENT)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not open directory \"%s\": %m", data_dir));

		LWLockRelease(tde_lwlock_enc_keys());
		return;
	}

	while ((de = ReadDir(dir, data_dir)) != NULL)
	{
		Oid			dbOid;
		int			n = 0;

		if (sscanf(de->d_name, "%u%n", &dbOid, &n) != 1 || n == 0)
			continue;

		if (strcmp(de->d_name + n, PG_TDE_DB_DIR_ROTATE_SUFFIX) == 0)
			rotate_dirs = lappend_oid(rotate_dirs, dbOid);
	}

	FreeDir(dir);

	foreach_oid(dbOid, rotate_dirs)
	{
		char		db_dir[MAXPGPATH];
		char		new_dir[MAXPGPATH];
		char		old_dir[MAXPGPATH];

		pg_tde_set_db_dir_path(dbOid, "", db_dir);
		pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_ROTATE_SUFFIX, new_dir);
		pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_OLD_SUFFIX, old_dir);

		if (access(db_dir, F_OK) == 0 || access(old_dir, F_OK) != 0)
			continue;

		ereport(LOG,
				errmsg("finishing interrupted principal key rotation for database %u", dbOid));

		if (rename(new_dir, db_dir) < 0)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not rename tde directory \"%s\" to \"%s\": %m",
						   new_dir, db_dir));
		fsync_fname(data_dir, true);
	}

	LWLockRelease(tde_lwlock_enc_keys());

	list_free(rotate_dirs);
}

/*
 * It doesn't overwrite an existing principal key. The file may already hold a
 * newer (rotated) key when we're replaying an old record.
 */
void
pg_tde_save_principal_key_redo(const TDESignedPrincipalKeyInfo *signed_key_info)
{
	char		pkey_path[MAXPGPATH];

	pg_tde_set_pkey_file_path(signed_key_info->data.databaseId, pkey_path);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);

	if (access(pkey_path, F_OK) != 0)
		pg_tde_save_signed_principal_key(signed_key_info);

	LWLockRelease(tde_lwlock_enc_keys());
}

/*
 * Creates a new file and saves the principal key information.
 *
 * If the file already exists, it will be rewritten. Errors out if the database
 * has encrypted relations, as their keys are encrypted with the existing
 * principal key.
 *
 * The caller must have an EXCLUSIVE LOCK on the files before calling this function.
 *
 * write_xlog: if true, the function will write an XLOG record about the
 * principal key addition. We may want to skip this during server recovery/startup
 * or in some other cases when WAL writes are not allowed.
 */
void
pg_tde_save_principal_key(const TDEPrincipalKey *principal_key, bool write_xlog)
{
	TDESignedPrincipalKeyInfo signed_key_info;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	/*
	 * Should not happen, but if it does, the existing keys and encrypted data
	 * become unreadable. So better be safe.
	 */
	if (pg_tde_count_encryption_keys(principal_key->keyInfo.databaseId, InvalidOid) != 0)
		ereport(ERROR,
				errcode(ERRCODE_OBJECT_IN_USE),
				errmsg("cannot set principal key of database %u", principal_key->keyInfo.databaseId),
				errdetail("There are encrypted relations in the database."));

	pg_tde_sign_principal_key_info(&signed_key_info, principal_key);

	if (write_xlog)
	{
		XLogBeginInsert();
		XLogRegisterData((char *) &signed_key_info, sizeof(TDESignedPrincipalKeyInfo));
		XLogInsert(RM_TDERMGR_ID, XLOG_TDE_ADD_PRINCIPAL_KEY);
	}

	pg_tde_save_signed_principal_key(&signed_key_info);
}

/*
 * Removes the key file of the relation.
 *
 * This function is called by the pg_tde SMGR when storage is unlinked on
 * transaction commit/abort.
 *
 * Errors are reported as warnings, like md.c does when unlinking relation
 * files, since an error after the commit record is a PANIC. The removal isn't
 * fsync'd either: should the file come back after a crash, the replay of the
 * relation drop removes it again.
 */
void
pg_tde_delete_rel_key(const RelFileLocator rlocator)
{
	char		file_path[MAXPGPATH];

	pg_tde_set_key_file_path(rlocator, file_path);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);

	if (unlink(file_path) < 0 && errno != ENOENT)
		ereport(WARNING,
				errcode_for_file_access(),
				errmsg("could not remove tde file \"%s\": %m", file_path));

	LWLockRelease(tde_lwlock_enc_keys());
}

/*
 * Re-encrypts the relation key in old_path with the new principal key and
 * writes it to new_path.
 */
static void
pg_tde_rotate_rel_key(const char *old_path, const char *new_path,
					  const RelFileLocator *rlocator,
					  const TDEPrincipalKey *old_principal_key,
					  const TDEPrincipalKey *new_principal_key)
{
	TDESmgrKeyEntry key_entry;
	TDESmgrKeyEntry new_key_entry = {0};
	InternalKey *rel_key_data;

	pg_tde_read_key_file(old_path, &key_entry);

	rel_key_data = tde_decrypt_rel_key(old_principal_key, &key_entry, rlocator);
	pg_tde_initialize_key_entry(&new_key_entry, new_principal_key, rlocator, rel_key_data);
	pfree(rel_key_data);

	pg_tde_write_file(new_path, &new_key_entry, sizeof(TDESmgrKeyEntry));
}

/*
 * Rotate keys and generates the WAL record for it.
 */
void
pg_tde_perform_rotate_key(const TDEPrincipalKey *principal_key, const TDEPrincipalKey *new_principal_key, bool write_xlog)
{
	Oid			dbOid = new_principal_key->keyInfo.databaseId;
	const char *data_dir = pg_tde_get_data_dir();
	char		db_dir[MAXPGPATH];
	char		new_dir[MAXPGPATH];
	char		old_dir[MAXPGPATH];
	char		old_path[MAXPGPATH];
	char		new_path[MAXPGPATH];
	List	   *key_files;
	TDEFileHeader fheader;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));
	Assert(principal_key);
	/* This function cannot be used to rotate the server key. */
	Assert(principal_key->keyInfo.databaseId != GLOBAL_DATA_TDE_OID);
	Assert(principal_key->keyInfo.databaseId == dbOid);

	pg_tde_set_db_dir_path(dbOid, "", db_dir);
	pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_ROTATE_SUFFIX, new_dir);
	pg_tde_set_db_dir_path(dbOid, PG_TDE_DB_DIR_OLD_SUFFIX, old_dir);

	/* Should have been created along with the current principal key file */
	Assert(access(db_dir, F_OK) == 0);

	/* Clean up leftovers of a rotation that failed with an error, if any */
	pg_tde_remove_dir_if_exists(new_dir);
	pg_tde_remove_dir_if_exists(old_dir);

	/*
	 * When replaying, there is nothing to do if the database already uses the
	 * new key. E.g. the rotation was finished on start and now its WAL record
	 * is replayed.
	 */
	if (!write_xlog && pg_tde_is_current_principal_key(dbOid, new_principal_key))
		return;

	if (MakePGDirectory(new_dir) < 0)
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not create tde directory \"%s\": %m", new_dir));

	fheader.file_version = PG_TDE_SMGR_FILE_MAGIC;
	pg_tde_sign_principal_key_info(&fheader.signed_key_info, new_principal_key);
	snprintf(new_path, MAXPGPATH, "%s/" PG_TDE_PRINCIPAL_KEY_FILE, new_dir);
	pg_tde_write_file(new_path, &fheader, sizeof(TDEFileHeader));
	fsync_fname(new_dir, true);
	fsync_fname(data_dir, true);

	key_files = pg_tde_list_key_files(dbOid, InvalidOid);
	foreach_ptr(char, file_name, key_files)
	{
		RelFileLocator rloc = {.dbOid = dbOid};
		bool		parsed PG_USED_FOR_ASSERTS_ONLY;

		parsed = pg_tde_parse_key_file_name(file_name, &rloc.spcOid, &rloc.relNumber);
		Assert(parsed);

		snprintf(old_path, MAXPGPATH, "%s/%s", db_dir, file_name);
		snprintf(new_path, MAXPGPATH, "%s/%s", new_dir, file_name);

		pg_tde_rotate_rel_key(old_path, new_path, &rloc, principal_key, new_principal_key);
	}
	list_free_deep(key_files);

	fsync_fname(new_dir, true);

	if (write_xlog)
	{
		XLogPrincipalKeyRotate xlrec;
		XLogRecPtr	lsn;

		/* Assigning an xid may fail, hence should be out of the critical section */
		GetTopTransactionId();

		START_CRIT_SECTION();

		Assert((MyProc->delayChkptFlags & DELAY_CHKPT_START) == 0);
		MyProc->delayChkptFlags |= DELAY_CHKPT_START;

		xlrec.databaseId = new_principal_key->keyInfo.databaseId;
		xlrec.keyringId = new_principal_key->keyInfo.keyringId;
		memcpy(xlrec.keyName, new_principal_key->keyInfo.name, sizeof(new_principal_key->keyInfo.name));

		XLogBeginInsert();
		XLogRegisterData((char *) &xlrec, sizeof(XLogPrincipalKeyRotate));
		lsn = XLogInsert(RM_TDERMGR_ID, XLOG_TDE_ROTATE_PRINCIPAL_KEY);

		XLogFlush(lsn);
	}

	if (rename(db_dir, old_dir) < 0)
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not rename tde directory \"%s\" to \"%s\": %m",
					   db_dir, old_dir));


	fsync_fname(data_dir, true);

	if (rename(new_dir, db_dir) < 0)
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not rename tde directory \"%s\" to \"%s\": %m",
					   new_dir, db_dir));
	fsync_fname(data_dir, true);

	if (write_xlog)
	{
		MyProc->delayChkptFlags &= ~DELAY_CHKPT_START;

		END_CRIT_SECTION();
	}

	/* If it fails, it gets removed on the next rotation */
	if (!rmtree(old_dir, true))
		ereport(WARNING,
				errmsg("could not remove tde directory \"%s\"", old_dir));
}

void
pg_tde_delete_principal_key_redo(Oid dbOid)
{
	char		pkey_path[MAXPGPATH];

	pg_tde_set_pkey_file_path(dbOid, pkey_path);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);
	durable_unlink(pkey_path, WARNING);
	LWLockRelease(tde_lwlock_enc_keys());
}

/*
 * Deletes the principal key for the database. Errors out if there are still
 * encrypted relations in the database.
 */
void
pg_tde_delete_principal_key(Oid dbOid)
{
	char		pkey_path[MAXPGPATH];

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	if (pg_tde_count_encryption_keys(dbOid, InvalidOid) != 0)
		ereport(ERROR,
				errcode(ERRCODE_OBJECT_IN_USE),
				errmsg("cannot delete principal key of database %u", dbOid),
				errdetail("There are encrypted relations in the database."));

	pg_tde_set_pkey_file_path(dbOid, pkey_path);

	XLogBeginInsert();
	XLogRegisterData((char *) &dbOid, sizeof(Oid));
	XLogInsert(RM_TDERMGR_ID, XLOG_TDE_DELETE_PRINCIPAL_KEY);

	durable_unlink(pkey_path, ERROR);
}

#endif							/* !FRONTEND */

void
pg_tde_sign_principal_key_info(TDESignedPrincipalKeyInfo *signed_key_info, const TDEPrincipalKey *principal_key)
{
	signed_key_info->data = principal_key->keyInfo;

	if (!RAND_bytes(signed_key_info->sign_iv, MAP_ENTRY_IV_SIZE))
		ereport(ERROR,
				errcode(ERRCODE_INTERNAL_ERROR),
				errmsg("could not generate iv for key map: %s", ERR_error_string(ERR_get_error(), NULL)));

	AesGcmEncrypt(principal_key->keyData, principal_key->keyLength,
				  signed_key_info->sign_iv, MAP_ENTRY_IV_SIZE,
				  (unsigned char *) &signed_key_info->data, sizeof(signed_key_info->data),
				  (unsigned char *) "", 0,
				  (unsigned char *) "",
				  signed_key_info->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE);
}

static void
pg_tde_initialize_key_entry(TDESmgrKeyEntry *key_entry, const TDEPrincipalKey *principal_key, const RelFileLocator *rlocator, const InternalKey *rel_key_data)
{
	TDESmgrKeyAAD aad;

	key_entry->file_version = PG_TDE_SMGR_FILE_MAGIC;
	memcpy(key_entry->key_base_iv, rel_key_data->base_iv, INTERNAL_KEY_IV_LEN);

	Assert(rel_key_data->key_len == 16 || rel_key_data->key_len == 32);
	key_entry->cipher = rel_key_data->key_len == 32 ? CIPHER_AES_256 : CIPHER_AES_128;	/* We support only those
																						 * for now */

	pg_tde_set_key_aad(&aad, key_entry->cipher, rlocator);

	if (!RAND_bytes(key_entry->entry_iv, MAP_ENTRY_IV_SIZE))
		ereport(ERROR,
				errcode(ERRCODE_INTERNAL_ERROR),
				errmsg("could not generate iv for key map: %s", ERR_error_string(ERR_get_error(), NULL)));

	AesGcmEncrypt(principal_key->keyData, principal_key->keyLength,
				  key_entry->entry_iv, MAP_ENTRY_IV_SIZE,
				  (unsigned char *) &aad, sizeof(TDESmgrKeyAAD),
				  rel_key_data->key, rel_key_data->key_len,
				  key_entry->encrypted_key_data,
				  key_entry->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE);
}

/*
 * Reads a relation key file. Fails if the file can't be read or is corrupted.
 */
static void
pg_tde_read_key_file(const char *file_path, TDESmgrKeyEntry *key_entry)
{
	int			fd;
	off_t		bytes_read;

	fd = OpenTransientFile(file_path, O_RDONLY | PG_BINARY);

	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", file_path));
	}

	bytes_read = pg_pread(fd, key_entry, sizeof(TDESmgrKeyEntry), 0);
	if (bytes_read < 0)
	{
		int			save_errno = errno;

		/* not to leak on frontend */
		CloseTransientFile(fd);
		errno = save_errno;
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", file_path));
	}
	CloseTransientFile(fd);

	if (bytes_read != sizeof(TDESmgrKeyEntry))
	{
		ereport(ERROR,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("could not read tde file \"%s\": read %zd of %zu",
					   file_path, (ssize_t) bytes_read, sizeof(TDESmgrKeyEntry)));
	}

	if (FILEMAGIC_TYPE(key_entry->file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(ERROR,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("key file \"%s\" is corrupted or has wrong version", file_path),
				errdetail("Getting relation key from the file."));
	}
}

/*
 * Reads the key file of the relation into key_entry. Returns false if the
 * relation has no key file.
 */
static bool
pg_tde_read_key_entry(const RelFileLocator *rlocator, TDESmgrKeyEntry *key_entry)
{
	char		file_path[MAXPGPATH];

	Assert(rlocator != NULL);
	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_SHARED) || LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	pg_tde_set_key_file_path(*rlocator, file_path);

	if (access(file_path, F_OK) == -1)
		return false;

	pg_tde_read_key_file(file_path, key_entry);

	return true;
}

#ifndef FRONTEND

/*
 * Parses the name of a relation key file. Returns false if it isn't one.
 */
static bool
pg_tde_parse_key_file_name(const char *name, Oid *spcOid, RelFileNumber *relNumber)
{
	int			n = 0;

	return sscanf(name, PG_TDE_KEY_FILENAME "%n", spcOid, relNumber, &n) == 2 &&
		n != 0 && name[n] == '\0';
}

/*
 * Lists names of the relation key files of the database. If spcOid is
 * InvalidOid, files of all the tablespaces are listed, otherwise only the
 * ones of the given tablespace. The caller is responsible for freeing the list
 * with list_free_deep().
 */
static List *
pg_tde_list_key_files(Oid dbOid, Oid spcOid)
{
	char		db_dir[MAXPGPATH];
	DIR		   *dir;
	struct dirent *de;
	List	   *files = NIL;

	pg_tde_set_db_dir_path(dbOid, "", db_dir);

	dir = AllocateDir(db_dir);

	if (dir == NULL)
	{
		if (errno != ENOENT)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not open directory \"%s\": %m", db_dir));

		return NIL;
	}

	while ((de = ReadDir(dir, db_dir)) != NULL)
	{
		Oid			file_spcOid;
		RelFileNumber file_relNumber;

		if (!pg_tde_parse_key_file_name(de->d_name, &file_spcOid, &file_relNumber))
			continue;

		if (spcOid != InvalidOid && file_spcOid != spcOid)
			continue;

		files = lappend(files, pstrdup(de->d_name));
	}

	FreeDir(dir);

	return files;
}

/*
 * Counts number of encryption keys of the database.
 *
 * Does not check if files are valid.
 *
 * Works even if the database has no keys.
 */
int
pg_tde_count_encryption_keys(Oid dbOid, Oid spcOid)
{
	List	   *files;
	int			count;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_SHARED) || LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	files = pg_tde_list_key_files(dbOid, spcOid);
	count = list_length(files);

	list_free_deep(files);

	return count;
}

#endif							/* !FRONTEND */

bool
pg_tde_verify_principal_key_info(TDESignedPrincipalKeyInfo *signed_key_info, const KeyData *principal_key_data)
{
	return AesGcmDecrypt(principal_key_data->data, principal_key_data->len,
						 signed_key_info->sign_iv, MAP_ENTRY_IV_SIZE,
						 (unsigned char *) &signed_key_info->data, sizeof(signed_key_info->data),
						 (unsigned char *) "", 0,
						 (unsigned char *) "",
						 signed_key_info->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE);
}

static void
pg_tde_set_key_aad(TDESmgrKeyAAD *aad, uint32 cipher, const RelFileLocator *rlocator)
{
	memset(aad, 0, sizeof(TDESmgrKeyAAD));
	aad->cipher = cipher;
	aad->spcOid = rlocator->spcOid;
	aad->relNumber = rlocator->relNumber;
}

static InternalKey *
tde_decrypt_rel_key(const TDEPrincipalKey *principal_key, TDESmgrKeyEntry *key_entry,
					const RelFileLocator *rlocator)
{
	InternalKey *key = palloc_object(InternalKey);
	uint32		key_len = pg_tde_cipher_key_length(key_entry->cipher);
	TDESmgrKeyAAD aad;

	Assert(principal_key);

	pg_tde_set_key_aad(&aad, key_entry->cipher, rlocator);

	if (!AesGcmDecrypt(principal_key->keyData, principal_key->keyLength,
					   key_entry->entry_iv, MAP_ENTRY_IV_SIZE,
					   (unsigned char *) &aad, sizeof(TDESmgrKeyAAD),
					   key_entry->encrypted_key_data, key_len,
					   key->key,
					   key_entry->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE))
		ereport(ERROR,
				errmsg("Failed to decrypt key, incorrect principal key or corrupted key file"));

	memcpy(key->base_iv, key_entry->key_base_iv, INTERNAL_KEY_IV_LEN);
	key->key_len = key_len;

	return key;
}

/*
 * Get the principal key from the key file. The caller must hold
 * a LW_SHARED or higher lock on files before calling this function.
 */
TDESignedPrincipalKeyInfo *
pg_tde_get_principal_key_info(Oid dbOid)
{
	char		pkey_path[MAXPGPATH];

	pg_tde_set_pkey_file_path(dbOid, pkey_path);

	return pg_tde_read_principal_key_file(pkey_path);
}

/*
 * Reads the principal key file. Returns NULL if there is no such file.
 */
static TDESignedPrincipalKeyInfo *
pg_tde_read_principal_key_file(const char *pkey_path)
{
	int			fd;
	TDESignedPrincipalKeyInfo *signed_key_info;
	off_t		bytes_read;
	TDEFileHeader fheader;

	fd = OpenTransientFile(pkey_path, O_RDONLY | PG_BINARY);

	/* The file does not exist. */
	if (fd < 0)
	{
		if (errno == ENOENT)
			return NULL;

		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", pkey_path));
	}

	bytes_read = pg_pread(fd, &fheader, sizeof(TDEFileHeader), 0);
	if (bytes_read < 0)
	{
		int			save_errno = errno;

		/* not to leak on frontend */
		CloseTransientFile(fd);
		errno = save_errno;
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", pkey_path));
	}
	CloseTransientFile(fd);

	if (bytes_read == 0)
		return NULL;

	if (bytes_read != sizeof(TDEFileHeader))
	{
		ereport(ERROR,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("could not read tde file \"%s\": read %zd of %zu",
					   pkey_path, (ssize_t) bytes_read, sizeof(TDEFileHeader)));
	}

	if (FILEMAGIC_TYPE(fheader.file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(ERROR,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("key file \"%s\" is corrupted or has wrong version", pkey_path),
				errdetail("Getting principal key from the file."));
	}

	signed_key_info = palloc_object(TDESignedPrincipalKeyInfo);
	*signed_key_info = fheader.signed_key_info;

	return signed_key_info;
}

/*
 * Figures out whether a relation is encrypted or not, but without trying to
 * decrypt the key if it is.
 */
bool
pg_tde_has_smgr_key(RelFileLocator rel)
{
	bool		result;
	char		file_path[MAXPGPATH];

	Assert(rel.relNumber != InvalidRelFileNumber);

	pg_tde_set_key_file_path(rel, file_path);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_SHARED);

	result = access(file_path, F_OK) == 0;

	LWLockRelease(tde_lwlock_enc_keys());
	return result;
}

/*
 * Reads the key file of the relation and decrypts the key.
 */
InternalKey *
pg_tde_get_smgr_key(RelFileLocator rel)
{
	TDESmgrKeyEntry key_entry;
	TDEPrincipalKey *principal_key;
	LWLock	   *lock_pk = tde_lwlock_enc_keys();
	InternalKey *rel_key;

	Assert(rel.relNumber != InvalidRelFileNumber);

	LWLockAcquire(lock_pk, LW_SHARED);

	if (!pg_tde_read_key_entry(&rel, &key_entry))
	{
		LWLockRelease(lock_pk);
		return NULL;
	}

	/*
	 * Get/generate a principal key, create the key for relation and get the
	 * encrypted key with bytes to write
	 *
	 * We should hold the lock until the internal key is loaded to be sure the
	 * retrieved key was encrypted with the obtained principal key. Otherwise,
	 * the next may happen: - GetPrincipalKey returns key "PKey_1". - Some
	 * other process rotates the Principal key and re-encrypt an Internal key
	 * with "PKey_2". - We read the Internal key and decrypt it with "PKey_1"
	 * (that's what we've got). As the result we return an invalid Internal
	 * key.
	 */
	principal_key = GetPrincipalKey(rel.dbOid, LW_SHARED);
	if (principal_key == NULL)
		ereport(ERROR,
				errmsg("principal key not configured"),
				errhint("Use pg_tde_set_key_using_database_key_provider() or pg_tde_set_key_using_global_key_provider() to configure one."));
	rel_key = tde_decrypt_rel_key(principal_key, &key_entry, &rel);

	/* principal_key may point to the cache, which needs the lock held */
	if (principal_key->keyLength != rel_key->key_len)
	{
		ereport(LOG,
				errmsg("length \"%u\" of principal key \"%s\" does not match the length \"%d\" of the internal key", principal_key->keyLength, principal_key->keyInfo.name, rel_key->key_len),
				errhint("Create a new principal key and set it instead of the current one."));
	}

	LWLockRelease(lock_pk);

#ifdef FRONTEND
	/* There is no principal key cache in the frontend. */
	pfree(principal_key);
#endif

	return rel_key;
}
