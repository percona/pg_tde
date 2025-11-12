/*
 * Main file: setup GUCs, shared memory, hooks and other general-purpose
 * routines.
 */

#include "postgres.h"

#include "access/tableam.h"
#include "access/xlog.h"
#include "access/xloginsert.h"
#include "funcapi.h"
#include "miscadmin.h"
#include "storage/ipc.h"
#include "storage/lwlock.h"
#include "storage/shmem.h"
#include "utils/builtins.h"
#include "utils/percona.h"

#include "access/pg_tde_tdemap.h"
#include "access/pg_tde_xlog.h"
#include "access/pg_tde_xlog_smgr.h"
#include "catalog/tde_global_space.h"
#include "catalog/tde_principal_key.h"
#include "encryption/enc_aes.h"
#include "keyring/keyring_api.h"
#include "keyring/keyring_file.h"
#include "keyring/keyring_kmip.h"
#include "keyring/keyring_vault.h"
#include "pg_tde.h"
#include "pg_tde_event_capture.h"
#include "pg_tde_guc.h"
#include "smgr/pg_tde_smgr.h"

PG_MODULE_MAGIC;

#define KEYS_VERSION_FILE	"keys_version"

typedef struct keys_version_info
{
	int32		smgr_version;
	int32		wal_version;
} keys_version_info;

static void pg_tde_init_data_dir(void);
static void pg_tde_migrate_internal_keys(void);

static shmem_startup_hook_type prev_shmem_startup_hook = NULL;
static shmem_request_hook_type prev_shmem_request_hook = NULL;

PG_FUNCTION_INFO_V1(pg_tde_extension_initialize);
PG_FUNCTION_INFO_V1(pg_tde_version);
PG_FUNCTION_INFO_V1(pg_tdeam_handler);

static void
tde_shmem_request(void)
{
	Size		sz = 0;

	sz = add_size(sz, PrincipalKeyShmemSize());
	sz = add_size(sz, TDESmgrShmemSize());
	sz = add_size(sz, TDEXLogSmgrShmemSize());

	if (prev_shmem_request_hook)
		prev_shmem_request_hook();

	RequestAddinShmemSpace(sz);
	RequestNamedLWLockTranche(TDE_TRANCHE_NAME, TDE_LWLOCK_COUNT);
	ereport(LOG, errmsg("tde_shmem_request: requested %ld bytes", sz));
}

static void
tde_shmem_startup(void)
{
	if (prev_shmem_startup_hook)
		prev_shmem_startup_hook();

	LWLockAcquire(AddinShmemInitLock, LW_EXCLUSIVE);

	KeyProviderShmemInit();
	PrincipalKeyShmemInit();
	TDESmgrShmemInit();
	TDEXLogSmgrShmemInit();

	TDEXLogSmgrInit();
	pg_tde_migrate_internal_keys();
	TDEXLogSmgrInitWrite(EncryptXLog, KeyLength);

	LWLockRelease(AddinShmemInitLock);
}

void
_PG_init(void)
{
	if (!process_shared_preload_libraries_in_progress)
	{
		/*
		 * psql/pg_restore continue on error by default, and change access
		 * methods using set default_table_access_method. This error needs to
		 * be FATAL and close the connection, otherwise these tools will
		 * continue execution and create unencrypted tables when the intention
		 * was to make them encrypted.
		 */
		elog(FATAL, "pg_tde can only be loaded at server startup. Restart required.");
	}

	check_percona_api_version();

	pg_tde_init_data_dir();
	AesInit();
	TdeGucInit();
	TdeEventCaptureInit();
	InstallFileKeyring();
	InstallVaultV2Keyring();
	InstallKmipKeyring();
	RegisterTdeRmgr();
	RegisterStorageMgr();

	prev_shmem_request_hook = shmem_request_hook;
	shmem_request_hook = tde_shmem_request;
	prev_shmem_startup_hook = shmem_startup_hook;
	shmem_startup_hook = tde_shmem_startup;
}

static void
extension_install(Oid databaseId)
{
	key_provider_startup_cleanup(databaseId);
	principal_key_startup_cleanup(databaseId);
}

Datum
pg_tde_extension_initialize(PG_FUNCTION_ARGS)
{
	XLogExtensionInstall xlrec;

	xlrec.database_id = MyDatabaseId;
	extension_install(xlrec.database_id);

	/*
	 * Also put this info in xlog, so we can replicate the same on the other
	 * side
	 */
	XLogBeginInsert();
	XLogRegisterData((char *) &xlrec, sizeof(XLogExtensionInstall));
	XLogInsert(RM_TDERMGR_ID, XLOG_TDE_INSTALL_EXTENSION);

	PG_RETURN_VOID();
}

void
extension_install_redo(XLogExtensionInstall *xlrec)
{
	extension_install(xlrec->database_id);
}

static void
pg_tde_create_keys_version_file(void)
{
	char		version_file_path[MAXPGPATH] = {0};
	int			fd;
	keys_version_info curr_version = {
		.smgr_version = PG_TDE_SMGR_FILE_MAGIC,
		.wal_version = PG_TDE_WAL_KEY_FILE_MAGIC,
	};

	join_path_components(version_file_path, PG_TDE_DATA_DIR, KEYS_VERSION_FILE);

	fd = OpenTransientFile(version_file_path, O_RDWR | O_CREAT | O_TRUNC | PG_BINARY);

	if (pg_pwrite(fd, &curr_version, sizeof(keys_version_info), 0) != sizeof(keys_version_info))
	{
		/*
		 * The worst that may happen is that we will re-scan all *_keys on the
		 * next start. So a failed write isn't worth aborting the cluster
		 * start.
		 */
		ereport(WARNING,
				errcode_for_file_access(),
				errmsg("failed to write keys version file \"%s\": %m", version_file_path));
	}

	CloseTransientFile(fd);
}

/* Creates a tde directory for internal files if not exists */
static void
pg_tde_init_data_dir(void)
{
	if (access(PG_TDE_DATA_DIR, F_OK) == -1)
	{
		if (MakePGDirectory(PG_TDE_DATA_DIR) < 0)
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not create tde directory \"%s\": %m",
						   PG_TDE_DATA_DIR));

		pg_tde_create_keys_version_file();
	}
}

/* Migrate *_keys files to the new format if needed. */
static void
pg_tde_migrate_internal_keys(void)
{
	char		version_file_path[MAXPGPATH] = {0};
	keys_version_info curr_version;
	int			fd;

	join_path_components(version_file_path, PG_TDE_DATA_DIR, KEYS_VERSION_FILE);

	if (access(version_file_path, F_OK) == 0)
	{
		fd = OpenTransientFile(version_file_path, O_RDONLY | PG_BINARY);

		if (pg_pread(fd, &curr_version, sizeof(keys_version_info), 0) != sizeof(keys_version_info))
		{
			ereport(FATAL,
					errcode_for_file_access(),
					errmsg("internal keys version file \"%s\" is corrupted: %m", version_file_path),
					errhint("Try to remove the file and restart server."));
		}

		CloseTransientFile(fd);

		/* All is up-to-date, nothing to do */
		if (curr_version.smgr_version == PG_TDE_SMGR_FILE_MAGIC &&
			curr_version.wal_version == PG_TDE_WAL_KEY_FILE_MAGIC)
			return;
	}

	pg_tde_update_wal_keys_file();
	pg_tde_migrate_smgr_keys_file();

	pg_tde_create_keys_version_file();
}

/* Returns package version */
Datum
pg_tde_version(PG_FUNCTION_ARGS)
{
	PG_RETURN_TEXT_P(cstring_to_text(PG_TDE_VERSION_STRING));
}

Datum
pg_tdeam_handler(PG_FUNCTION_ARGS)
{
	PG_RETURN_POINTER(GetHeapamTableAmRoutine());
}
