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
#if PG_VERSION_NUM >= 180000
#include "storage/aio.h"
#endif

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

static void pg_tde_init_data_dir(void);

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
	sz = add_size(sz, TDEXLogEncryptStateSize());

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
	TDEXLogShmemInit();
	TDEXLogSmgrInit();
	TDEXLogSmgrInitWrite(EncryptXLog);

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

#if PG_VERSION_NUM >= 180000
	if (io_method != IOMETHOD_SYNC)
	{
		elog(FATAL, "pg_tde currently doesn't support Postgres 18 AIO. Disable it using 'io_method = sync' and restart the server.");
	}
#endif

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
	}
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
