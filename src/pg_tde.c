/*-------------------------------------------------------------------------
 *
 * pg_tde.c
 *      Main file: setup GUCs, shared memory, hooks and other general-purpose
 *      routines.
 *
 * IDENTIFICATION
 *    contrib/pg_tde/src/pg_tde.c
 *
 *-------------------------------------------------------------------------
 */

#include "postgres.h"
#include "funcapi.h"
#include "transam/pg_tde_xact_handler.h"
#include "miscadmin.h"
#include "storage/ipc.h"
#include "storage/lwlock.h"
#include "storage/shmem.h"
#include "access/pg_tde_ddl.h"
#include "encryption/enc_aes.h"
#include "access/pg_tde_tdemap.h"

#include "keyring/keyring_config.h"
#include "keyring/keyring_api.h"
#include "common/pg_tde_shmem.h"
#include "catalog/tde_master_key.h"
#include "keyring/keyring_file.h"

PG_MODULE_MAGIC;
void _PG_init(void);

static shmem_startup_hook_type prev_shmem_startup_hook = NULL;
static shmem_request_hook_type prev_shmem_request_hook = NULL;

static void
tde_shmem_request(void)
{
	Size sz = TdeRequiredSharedMemorySize();
	int required_locks = TdeRequiredLocksCount();
	if (prev_shmem_request_hook)
		prev_shmem_request_hook();
	RequestAddinShmemSpace(sz);
	ereport(LOG, (errmsg("tde_shmem_request: requested %ld bytes", sz)));

	RequestNamedLWLockTranche("pg_tde_tranche", required_locks);
}

static void
tde_shmem_startup(void)
{
	if (prev_shmem_startup_hook)
		prev_shmem_startup_hook();

	TdeShmemInit();
	AesInit();
}

void _PG_init(void)
{
	if (!process_shared_preload_libraries_in_progress)
	{
		elog(WARNING, "pg_tde can only be loaded at server startup. Restart required.");
	}

	keyringRegisterVariables();
	InitializeMasterKeyInfo();

	prev_shmem_request_hook = shmem_request_hook;
	shmem_request_hook = tde_shmem_request;
	prev_shmem_startup_hook = shmem_startup_hook;
	shmem_startup_hook = tde_shmem_startup;

	RegisterXactCallback(pg_tde_xact_callback, NULL);
	RegisterSubXactCallback(pg_tde_subxact_callback, NULL);
	SetupTdeDDLHooks();
	InstallFileKeyring();
	RegisterCustomRmgr(RM_TDERMGR_ID, &pg_tde_rmgr);
}
