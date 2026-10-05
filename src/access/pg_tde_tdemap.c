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
#include "common/pg_tde_utils.h"
#include "encryption/enc_aes.h"
#include "encryption/enc_tde.h"
#include "pg_tde.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

#define PG_TDE_PRINCIPAL_KEY_FILENAME	"%u_tde_pkey"
#define PG_TDE_KEY_FILE_SUFFIX		"_tde_key"
#define PG_TDE_KEY_FILE_SUFFIX_LEN	(sizeof(PG_TDE_KEY_FILE_SUFFIX) - 1)
#define PG_TDE_MAP_FILENAME			"%s" PG_TDE_KEY_FILE_SUFFIX

/*
 * A principal key rotation is in progress, needed for the crash recovery.
 * In PG_TDE_DATA_DIR so that the startup check doesn't have to scan all
 * databases. Rotations are serialized by tde_lwlock_enc_keys(). Holds the
 * target principal key.
 */
#define PG_TDE_KEY_ROTATE_INPROGRESS_FILE	PG_TDE_DATA_DIR "/tde_rotate.inprogress"

/*
 * The key files of a database deletion is in progress. Same as for the
 * rotation, needed for the crash recovery and there is only one as deletions
 * are serialized by tde_lwlock_enc_keys(). Holds the database oid.
 */
#define PG_TDE_KEY_DELETE_INPROGRESS_FILE	PG_TDE_DATA_DIR "/tde_delete.inprogress"

typedef struct TDEDeleteInProgress
{
	int32		file_version;
	Oid			dbOid;
} TDEDeleteInProgress;

typedef struct TDEFileHeader
{
	int32		file_version;
	TDESignedPrincipalKeyInfo signed_key_info;
} TDEFileHeader;

/* SMGR key on disk */
typedef struct TDESmgrKeyEntry
{
	TDEFileHeader	header;
	uint32		cipher;			/* Part of AAD. Cipher type. We support only
								 * AES_128 and AES_256 for now. */
	Oid			spcOid;			/* Part of AAD */
	RelFileNumber relNumber;	/* Part of AAD */

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

#define	PG_TDE_KEY_AAD_OFFSET	offsetof(TDESmgrKeyEntry, cipher)
#define	PG_TDE_KEY_AAD_LEN		(offsetof(TDESmgrKeyEntry, entry_iv) - sizeof(TDEFileHeader))

static void pg_tde_set_db_file_path(RelFileLocator rel, char *path);
static void pg_tde_set_pkey_file_path(Oid dbOid, char *path);
static bool pg_tde_read_key_entry(const RelFileLocator *rlocator, TDESmgrKeyEntry *map_entry);
static InternalKey *tde_decrypt_rel_key(const TDEPrincipalKey *principal_key, TDESmgrKeyEntry *map_entry);
static void pg_tde_initialize_map_entry(TDESmgrKeyEntry *map_entry, const TDEPrincipalKey *principal_key, const RelFileLocator *rlocator, const InternalKey *rel_key_data);
static void pg_tde_durable_write_file(const char *path, const void *data, size_t len);
#ifndef FRONTEND
static bool pg_tde_principal_key_info_eq(const TDEPrincipalKeyInfo *a, const TDEPrincipalKeyInfo *b);
static void pg_tde_rotate_rel_key(const char *file_path, const TDEPrincipalKey *old_principal_key, const TDEPrincipalKey *new_principal_key);
static void pg_tde_rotate_db_keys(const TDEPrincipalKey *principal_key, const TDEPrincipalKey *new_principal_key);
static TDEPrincipalKey *pg_tde_finish_pending_rotation(void);
static List *pg_tde_list_keys_in_db_dir(Oid dbOid, Oid spcOid);
static List *pg_tde_list_key_files(Oid dbOid, Oid spcOid);
static void pg_tde_save_signed_principal_key(const TDESignedPrincipalKeyInfo *signed_key_info);
static bool pg_tde_read_rotate_inprogress(TDEFileHeader *fheader);
static void pg_tde_delete_db_key_files(Oid dbOid);
static void pg_tde_finish_pending_delete(void);
#endif

static void
pg_tde_durable_write_file(const char *path, const void *data, size_t len)
{
	char		path_tmp[MAXPGPATH];
	int			fd;

	snprintf(path_tmp, MAXPGPATH, "%s.r", path);

	fd = OpenTransientFile(path_tmp, O_RDWR | O_CREAT | O_TRUNC | PG_BINARY);

	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not create tde file \"%s\": %m", path_tmp));
	}

	if (pg_pwrite(fd, data, len, 0) != len)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not write tde file \"%s\": %m", path_tmp));
	}

	if (pg_fsync(fd) != 0)
	{
		ereport(data_sync_elevel(ERROR),
				errcode_for_file_access(),
				errmsg("could not fsync tde file \"%s\": %m", path_tmp));
	}

	CloseTransientFile(fd);

	durable_rename(path_tmp, path, ERROR);
}

/*
 * Saves an internal key for the given relation. If replace_existing is false,
 * the function will not overwrite an existing key for the relation.
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

	pg_tde_set_db_file_path(rel, file_path);

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

	entry.header.file_version = PG_TDE_SMGR_FILE_MAGIC;

	pg_tde_sign_principal_key_info(&entry.header.signed_key_info, principal_key);
	pg_tde_initialize_map_entry(&entry, principal_key, &rel, rel_key_data);

#ifdef FRONTEND
	pfree(principal_key);
#endif

	pg_tde_durable_write_file(file_path, &entry, sizeof(TDESmgrKeyEntry));

	LWLockRelease(lock_pk);
}

#ifndef FRONTEND
/*
 * Checks for a rotate in-progress and reads it into fheader if it exists.
 * Returns false if there is none.
 */
static bool
pg_tde_read_rotate_inprogress(TDEFileHeader *fheader)
{
	int			fd;
	off_t		bytes_read;

	fd = OpenTransientFile(PG_TDE_KEY_ROTATE_INPROGRESS_FILE, O_RDONLY | PG_BINARY);

	if (fd < 0)
	{
		if (errno == ENOENT)
			return false;

		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", PG_TDE_KEY_ROTATE_INPROGRESS_FILE));
	}

	bytes_read = pg_pread(fd, fheader, sizeof(TDEFileHeader), 0);
	if (bytes_read < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", PG_TDE_KEY_ROTATE_INPROGRESS_FILE));
	}
	CloseTransientFile(fd);

	if (bytes_read != sizeof(TDEFileHeader) ||
		FILEMAGIC_TYPE(fheader->file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(FATAL,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("key rotation in-progress file \"%s\" is corrupted or has wrong version",
					   PG_TDE_KEY_ROTATE_INPROGRESS_FILE));
	}

	return true;
}

/*
 * Removes the relation key files and the principal key file of the database
 * and then the delete-in-progress file.
 *
 * Also cancels the database's unfinished rotation, if any. It would fail on
 * the next start otherwise as there are no keys to rotate anymore.
 */
static void
pg_tde_delete_db_key_files(Oid dbOid)
{
	char		pkey_path[MAXPGPATH];
	List	   *key_files;
	TDEFileHeader rotate_inprogress;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	if (pg_tde_read_rotate_inprogress(&rotate_inprogress) &&
		rotate_inprogress.signed_key_info.data.databaseId == dbOid)
		durable_unlink(PG_TDE_KEY_ROTATE_INPROGRESS_FILE, ERROR);

	key_files = pg_tde_list_key_files(dbOid, InvalidOid);
	foreach_ptr(char, file_path, key_files)
		durable_unlink(file_path, ERROR);
	list_free_deep(key_files);

	pg_tde_set_pkey_file_path(dbOid, pkey_path);
	if (access(pkey_path, F_OK) == 0)
		durable_unlink(pkey_path, ERROR);

	durable_unlink(PG_TDE_KEY_DELETE_INPROGRESS_FILE, ERROR);
}

/*
 * Finishes up the deletion left by a server crash or an error, if there
 * is any.
 */
static void
pg_tde_finish_pending_delete(void)
{
	int			fd;
	off_t		bytes_read;
	TDEDeleteInProgress inprogress;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	fd = OpenTransientFile(PG_TDE_KEY_DELETE_INPROGRESS_FILE, O_RDONLY | PG_BINARY);

	if (fd < 0)
	{
		/* No unfinished deletion, nothing to do */
		if (errno == ENOENT)
			return;

		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", PG_TDE_KEY_DELETE_INPROGRESS_FILE));
	}

	bytes_read = pg_pread(fd, &inprogress, sizeof(TDEDeleteInProgress), 0);
	if (bytes_read < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", PG_TDE_KEY_DELETE_INPROGRESS_FILE));
	}
	CloseTransientFile(fd);

	if (bytes_read != sizeof(TDEDeleteInProgress) ||
		FILEMAGIC_TYPE(inprogress.file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(FATAL,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("key deletion in-progress file \"%s\" is corrupted or has wrong version",
					   PG_TDE_KEY_DELETE_INPROGRESS_FILE));
	}

	ereport(LOG,
			errmsg("finishing interrupted deletion of keys for database %u",
				   inprogress.dbOid));

	pg_tde_delete_db_key_files(inprogress.dbOid);
}

/*
 * Deletes the key files for a given database.
 */
void
pg_tde_delete_tde_files(Oid dbOid)
{
	LWLock	   *lock_pk = tde_lwlock_enc_keys();
	TDEDeleteInProgress inprogress;

	LWLockAcquire(lock_pk, LW_EXCLUSIVE);

	/*
	 * A previous deletion might have failed with an error. Finish it first as
	 * we're about to overwrite its in-progress file.
	 */
	pg_tde_finish_pending_delete();

	inprogress.file_version = PG_TDE_SMGR_FILE_MAGIC;
	inprogress.dbOid = dbOid;
	pg_tde_durable_write_file(PG_TDE_KEY_DELETE_INPROGRESS_FILE, &inprogress, sizeof(TDEDeleteInProgress));

	pg_tde_delete_db_key_files(dbOid);

	LWLockRelease(lock_pk);
}

/*
 * Checks if there is an interrupted (by crash) deletion of the database keys
 * and finishes up one if there is.
 *
 * Should be called on server start.
 */
void
pg_tde_ensure_delete_on_start(void)
{
	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);
	pg_tde_finish_pending_delete();
	LWLockRelease(tde_lwlock_enc_keys());
}

static void
pg_tde_save_signed_principal_key(const TDESignedPrincipalKeyInfo *signed_key_info)
{
	char		pkey_path[MAXPGPATH];
	TDEFileHeader fheader;

	fheader.file_version = PG_TDE_SMGR_FILE_MAGIC;
	fheader.signed_key_info = *signed_key_info;

	pg_tde_set_pkey_file_path(signed_key_info->data.databaseId, pkey_path);

	pg_tde_durable_write_file(pkey_path, &fheader, sizeof(TDEFileHeader));
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
 * If the file already exists, it will be rewritten.
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
 */
void
pg_tde_delete_rel_key(const RelFileLocator rlocator)
{
	char		file_path[MAXPGPATH];

	pg_tde_set_db_file_path(rlocator, file_path);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);

	if (access(file_path, F_OK) == 0)
		durable_unlink(file_path, ERROR);

	LWLockRelease(tde_lwlock_enc_keys());
}

static bool
pg_tde_principal_key_info_eq(const TDEPrincipalKeyInfo *a, const TDEPrincipalKeyInfo *b)
{
	return a->databaseId == b->databaseId &&
		a->keyringId == b->keyringId &&
		a->creationTime.tv_sec == b->creationTime.tv_sec &&
		a->creationTime.tv_usec == b->creationTime.tv_usec &&
		strncmp(a->name, b->name, PRINCIPAL_KEY_NAME_LEN) == 0;
}

static void
pg_tde_rotate_rel_key(const char *file_path, const TDEPrincipalKey *old_principal_key, const TDEPrincipalKey *new_principal_key)
{
	TDESmgrKeyEntry map_entry;
	TDESmgrKeyEntry write_map_entry = {0};
	File		fd;
	InternalKey *rel_key_data;
	RelFileLocator rloc;

	fd = OpenTransientFile(file_path, O_RDONLY | PG_BINARY);
	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", file_path));
	}

	if (pg_pread(fd, &map_entry, sizeof(TDESmgrKeyEntry), 0) != sizeof(TDESmgrKeyEntry))
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", file_path));
	}
	CloseTransientFile(fd);

	/* Nothing to do, already has the new key */
	if (pg_tde_principal_key_info_eq(&map_entry.header.signed_key_info.data, &new_principal_key->keyInfo))
		return;

	rloc.spcOid = map_entry.spcOid;
	rloc.dbOid = new_principal_key->keyInfo.databaseId;
	rloc.relNumber = map_entry.relNumber;

	rel_key_data = tde_decrypt_rel_key(old_principal_key, &map_entry);
	pg_tde_initialize_map_entry(&write_map_entry, new_principal_key, &rloc, rel_key_data);
	pfree(rel_key_data);

	write_map_entry.header.file_version = PG_TDE_SMGR_FILE_MAGIC;
	pg_tde_sign_principal_key_info(&write_map_entry.header.signed_key_info, new_principal_key);

	pg_tde_durable_write_file(file_path, &write_map_entry, sizeof(TDESmgrKeyEntry));
}

/*
 * Re-encrypts all relation keys of the database with the new principal key
 * and makes it the database's principal key.
 *
 * Expects the rotate-in-progress file with the new principal key info to be
 * in place. Relation keys that are already encrypted with the new key are
 * skipped, so it is safe to call this again to finish an interrupted rotation.
 */
static void
pg_tde_rotate_db_keys(const TDEPrincipalKey *principal_key, const TDEPrincipalKey *new_principal_key)
{
	List	   *key_files;

	key_files = pg_tde_list_key_files(new_principal_key->keyInfo.databaseId, InvalidOid);
	foreach_ptr(char, file_path, key_files)
		pg_tde_rotate_rel_key(file_path, principal_key, new_principal_key);
	list_free_deep(key_files);

	/*
	 * If we crash between these two, the next start finds the in-progress
	 * file with the principal key file already holding the new key. All relation keys are
	 * skipped then and the rotation just gets finalized again.
	 */
	pg_tde_save_principal_key(new_principal_key, false);
	durable_unlink(PG_TDE_KEY_ROTATE_INPROGRESS_FILE, ERROR);
}

/*
 * Rotate keys and generates the WAL record for it.
 */
void
pg_tde_perform_rotate_key(const TDEPrincipalKey *principal_key, const TDEPrincipalKey *new_principal_key, bool write_xlog)
{
	TDEFileHeader fheader;
	TDEPrincipalKey *pending_key;
	Oid			dbOid = new_principal_key->keyInfo.databaseId;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));
	Assert(principal_key);
	/* This function cannot be used to rotate the server key. */
	Assert(principal_key->keyInfo.databaseId != GLOBAL_DATA_TDE_OID);
	Assert(principal_key->keyInfo.databaseId == dbOid);

	/*
	 * A previous rotation might have failed with an error. Finish it first as
	 * we're about to overwrite its in-progress file.
	 */
	pending_key = pg_tde_finish_pending_rotation();
	if (pending_key != NULL)
	{
		if (pending_key->keyInfo.databaseId == dbOid)
		{
			/*
			 * It was this database's rotation. Its target key is the current
			 * principal key now, not the one the caller passed. The caller
			 * refreshes the cache for this database afterwards.
			 */
			principal_key = pending_key;
		}
		else
		{
			/*
			 * The cached key of the other database is outdated now. Callers
			 * hold cache entries only of the database they rotate, so it is
			 * safe to drop this one.
			 */
			clear_principal_key_cache(pending_key->keyInfo.databaseId);
		}
	}

	/*
	 * Create the in-progress file with the new principal key. If we crash in
	 * the middle of the rotation, it will be finished on the next start by
	 * pg_tde_ensure_rotation_on_start().
	 */
	fheader.file_version = PG_TDE_SMGR_FILE_MAGIC;
	pg_tde_sign_principal_key_info(&fheader.signed_key_info, new_principal_key);

	pg_tde_durable_write_file(PG_TDE_KEY_ROTATE_INPROGRESS_FILE, &fheader, sizeof(TDEFileHeader));

	if (write_xlog)
	{
		XLogPrincipalKeyRotate xlrec;

		xlrec.databaseId = new_principal_key->keyInfo.databaseId;
		xlrec.keyringId = new_principal_key->keyInfo.keyringId;
		memcpy(xlrec.keyName, new_principal_key->keyInfo.name, sizeof(new_principal_key->keyInfo.name));

		XLogBeginInsert();
		XLogRegisterData((char *) &xlrec, sizeof(XLogPrincipalKeyRotate));
		XLogInsert(RM_TDERMGR_ID, XLOG_TDE_ROTATE_PRINCIPAL_KEY);
	}

	pg_tde_rotate_db_keys(principal_key, new_principal_key);

	if (pending_key != NULL)
		pfree(pending_key);
}

/*
 * Finishes up the rotation left by a server crash or an error, if there is
 * any. Returns the principal key the database was rotated to (palloc'd), or
 * NULL if there was nothing to finish.
 */
static TDEPrincipalKey *
pg_tde_finish_pending_rotation(void)
{
	TDEFileHeader fheader;
	TDESignedPrincipalKeyInfo *old_key_info;
	TDEPrincipalKey *principal_key;
	TDEPrincipalKey *new_principal_key;

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	/* No unfinished rotation */
	if (!pg_tde_read_rotate_inprogress(&fheader))
		return NULL;

	ereport(LOG,
			errmsg("finishing interrupted principal key rotation for database %u",
				   fheader.signed_key_info.data.databaseId));

	old_key_info = pg_tde_get_principal_key_info(fheader.signed_key_info.data.databaseId);
	if (old_key_info == NULL)
	{
		ereport(ERROR,
				errmsg("could not get principal key info for database %u",
					   fheader.signed_key_info.data.databaseId),
				errdetail("Failed to finish interrupted principal key rotation."));
	}

	principal_key = pg_tde_load_principal_key(old_key_info);
	new_principal_key = pg_tde_load_principal_key(&fheader.signed_key_info);

	pg_tde_rotate_db_keys(principal_key, new_principal_key);

	pfree(old_key_info);
	pfree(principal_key);

	return new_principal_key;
}

/*
 * Checks if there is an interrupted (by crash) rotation and finishes up one
 * if there is.
 *
 * Should be called on server start.
 */
void
pg_tde_ensure_rotation_on_start(void)
{
	TDEPrincipalKey *new_principal_key;

	/*
	 * A lock needed for EXEC_BACKEND, plus some functions expect it.
	 */
	LWLockAcquire(tde_lwlock_enc_keys(), LW_EXCLUSIVE);
	new_principal_key = pg_tde_finish_pending_rotation();
	LWLockRelease(tde_lwlock_enc_keys());

	if (new_principal_key != NULL)
		pfree(new_principal_key);
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
 * Deletes the principal key for the database. The caller should ensure there
 * are no encrypted relation in the database.
 */
void
pg_tde_delete_principal_key(Oid dbOid)
{
	char		pkey_path[MAXPGPATH];

	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));
	Assert(pg_tde_count_encryption_keys(dbOid, InvalidOid) == 0);

	pg_tde_set_pkey_file_path(dbOid, pkey_path);

	XLogBeginInsert();
	XLogRegisterData((char *) &dbOid, sizeof(Oid));
	XLogInsert(RM_TDERMGR_ID, XLOG_TDE_DELETE_PRINCIPAL_KEY);

	durable_unlink(pkey_path, ERROR);
}

#endif							/* !FRONTEND */

static void
pg_tde_set_db_file_path(RelFileLocator rel, char *path)
{
#if PG_VERSION_NUM >= 180000
	snprintf(path, MAXPGPATH, PG_TDE_MAP_FILENAME, relpathperm(rel, MAIN_FORKNUM).str);
#else
	char	   *rel_file_path = relpathperm(rel, MAIN_FORKNUM);

	snprintf(path, MAXPGPATH, PG_TDE_MAP_FILENAME, rel_file_path);
	pfree(rel_file_path);
#endif
}

static void
pg_tde_set_pkey_file_path(Oid dbOid, char *path)
{
	snprintf(path, MAXPGPATH, "%s/" PG_TDE_PRINCIPAL_KEY_FILENAME, pg_tde_get_data_dir(), dbOid);
}

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
pg_tde_initialize_map_entry(TDESmgrKeyEntry *key_entry, const TDEPrincipalKey *principal_key, const RelFileLocator *rlocator, const InternalKey *rel_key_data)
{
	key_entry->spcOid = rlocator->spcOid;
	key_entry->relNumber = rlocator->relNumber;
	memcpy(key_entry->key_base_iv, rel_key_data->base_iv, INTERNAL_KEY_IV_LEN);

	Assert(rel_key_data->key_len == 16 || rel_key_data->key_len == 32);
	key_entry->cipher = rel_key_data->key_len == 32 ? CIPHER_AES_256 : CIPHER_AES_128;	/* We support only those
																						 * for now */

	if (!RAND_bytes(key_entry->entry_iv, MAP_ENTRY_IV_SIZE))
		ereport(ERROR,
				errcode(ERRCODE_INTERNAL_ERROR),
				errmsg("could not generate iv for key map: %s", ERR_error_string(ERR_get_error(), NULL)));

	AesGcmEncrypt(principal_key->keyData, principal_key->keyLength,
				  key_entry->entry_iv, MAP_ENTRY_IV_SIZE,
				  (unsigned char *) key_entry + PG_TDE_KEY_AAD_OFFSET, PG_TDE_KEY_AAD_LEN,
				  rel_key_data->key, rel_key_data->key_len,
				  key_entry->encrypted_key_data,
				  key_entry->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE);
}

/*
 * Reads the key file of the relation into map_entry. Returns false if the
 * relation has no key file or it is incomplete.
 */
static bool
pg_tde_read_key_entry(const RelFileLocator *rlocator, TDESmgrKeyEntry *key_entry)
{
	char		file_path[MAXPGPATH];
	File		fd;
	off_t		bytes_read;

	Assert(rlocator != NULL);
	Assert(LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_SHARED) || LWLockHeldByMeInMode(tde_lwlock_enc_keys(), LW_EXCLUSIVE));

	pg_tde_set_db_file_path(*rlocator, file_path);

	if (access(file_path, F_OK) == -1)
		return false;

	fd = OpenTransientFile(file_path, O_RDONLY | PG_BINARY);

	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open tde file \"%s\": %m", file_path));
	}

	bytes_read = pg_pread(fd, key_entry, sizeof(TDESmgrKeyEntry), 0);
	CloseTransientFile(fd);

	if (bytes_read != sizeof(TDESmgrKeyEntry) ||
		FILEMAGIC_TYPE(key_entry->header.file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(FATAL,
				errcode_for_file_access(),
				errmsg("key file \"%s\" is corrupted or has wrong version: %m", file_path),
				errdetail("Getting relation key from the file."));

	}

	return true;
}

#ifndef FRONTEND

/*
 * Returns paths of the key files ("<relation path>_tde_key") of the given
 * database and tablespace. The paths are palloc'd.
 *
 * Returns NIL if the database has no directory in that tablespace.
 */
static List *
pg_tde_list_keys_in_db_dir(Oid dbOid, Oid spcOid)
{
	char	   *db_path = GetDatabasePath(dbOid, spcOid);
	DIR		   *dir;
	struct dirent *de;
	List	   *files = NIL;

	dir = AllocateDir(db_path);

	if (dir == NULL)
	{
		if (errno != ENOENT)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not open directory \"%s\": %m", db_path));

		pfree(db_path);
		return NIL;
	}

	while ((de = ReadDir(dir, db_path)) != NULL)
	{
		size_t		name_len = strlen(de->d_name);

		if (name_len > PG_TDE_KEY_FILE_SUFFIX_LEN &&
			strcmp(de->d_name + name_len - PG_TDE_KEY_FILE_SUFFIX_LEN,
				   PG_TDE_KEY_FILE_SUFFIX) == 0)
			files = lappend(files, psprintf("%s/%s", db_path, de->d_name));
	}

	FreeDir(dir);
	pfree(db_path);

	return files;
}

/*
 * Counts number of encryption keys of the database.
 *
 * Every encrypted relation has its own key file, hence we just count those
 * files in the database directories. If spcOid is InvalidOid, keys in all the
 * tablespaces are counted, otherwise only the ones in the given tablespace.
 *
 * Does not check if files are valid.
 */
int
pg_tde_count_encryption_keys(Oid dbOid, Oid spcOid)
{
	List	   *files = pg_tde_list_key_files(dbOid, spcOid);
	int			count = list_length(files);

	list_free_deep(files);

	return count;
}

/*
 * Lists paths of the key files of the database. If spcOid is InvalidOid, key
 * files in all the tablespaces are listed, otherwise only the ones in the
 * given tablespace. The caller is responsible for freeing the list with
 * list_free_deep().
 */
static List *
pg_tde_list_key_files(Oid dbOid, Oid spcOid)
{
	DIR		   *dir;
	struct dirent *de;
	List	   *files;

	if (spcOid != InvalidOid)
		return pg_tde_list_keys_in_db_dir(dbOid, spcOid);

	files = pg_tde_list_keys_in_db_dir(dbOid, DEFAULTTABLESPACE_OID);

	/* check custom tablespaces */
	dir = AllocateDir(PG_TBLSPC_DIR);

	if (dir == NULL)
	{
		if (errno != ENOENT)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not open directory \"%s\": %m", PG_TBLSPC_DIR));

		return files;
	}

	while ((de = ReadDir(dir, PG_TBLSPC_DIR)) != NULL)
	{
		Oid			tblspcOid = atooid(de->d_name);
		List	   *spc_files;

		/* skip ".", "..", etc. */
		if (tblspcOid == InvalidOid)
			continue;

		spc_files = pg_tde_list_keys_in_db_dir(dbOid, tblspcOid);
		files = list_concat(files, spc_files);
		list_free(spc_files);
	}

	FreeDir(dir);

	return files;
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

static InternalKey *
tde_decrypt_rel_key(const TDEPrincipalKey *principal_key, TDESmgrKeyEntry *map_entry)
{
	InternalKey *key = palloc_object(InternalKey);
	uint32		key_len = pg_tde_cipher_key_length(map_entry->cipher);

	Assert(principal_key);

	if (!AesGcmDecrypt(principal_key->keyData, principal_key->keyLength,
					   map_entry->entry_iv, MAP_ENTRY_IV_SIZE,
					   (unsigned char *) map_entry + PG_TDE_KEY_AAD_OFFSET, PG_TDE_KEY_AAD_LEN,
					   map_entry->encrypted_key_data, key_len,
					   key->key,
					   map_entry->aead_tag, MAP_ENTRY_AEAD_TAG_SIZE))
		ereport(ERROR,
				errmsg("Failed to decrypt key, incorrect principal key or corrupted key file"));

	memcpy(key->base_iv, map_entry->key_base_iv, INTERNAL_KEY_IV_LEN);
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
	int			fd;
	TDESignedPrincipalKeyInfo *signed_key_info;
	off_t		bytes_read;
	TDEFileHeader fheader;

	pg_tde_set_pkey_file_path(dbOid, pkey_path);

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
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not read tde file \"%s\": %m", pkey_path));
	}
	CloseTransientFile(fd);

	if (bytes_read == 0)
		return NULL;

	if (bytes_read != sizeof(TDEFileHeader) ||
		FILEMAGIC_TYPE(fheader.file_version) != FILEMAGIC_TYPE(PG_TDE_SMGR_FILE_MAGIC))
	{
		ereport(FATAL,
				errcode_for_file_access(),
				errmsg("key file \"%s\" is corrupted or has wrong version: %m", pkey_path),
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
	TDESmgrKeyEntry map_entry;

	Assert(rel.relNumber != InvalidRelFileNumber);

	LWLockAcquire(tde_lwlock_enc_keys(), LW_SHARED);

	result = pg_tde_read_key_entry(&rel, &map_entry);

	LWLockRelease(tde_lwlock_enc_keys());
	return result;
}

/*
 * Reads the map entry of the relation and decrypts the key.
 */
InternalKey *
pg_tde_get_smgr_key(RelFileLocator rel)
{
	TDESmgrKeyEntry map_entry;
	TDEPrincipalKey *principal_key;
	LWLock	   *lock_pk = tde_lwlock_enc_keys();
	InternalKey *rel_key;

	Assert(rel.relNumber != InvalidRelFileNumber);

	LWLockAcquire(lock_pk, LW_SHARED);

	if (!pg_tde_read_key_entry(&rel, &map_entry))
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
	rel_key = tde_decrypt_rel_key(principal_key, &map_entry);

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
