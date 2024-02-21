/*-------------------------------------------------------------------------
 *
 * tde_master_key.c
 *      Deals with the tde master key configuration catalog
 *      routines.
 *
 * IDENTIFICATION
 *    contrib/pg_tde/src/catalog/tde_master_key.c
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"
#include "catalog/tde_master_key.h"
#include "keyring/keyring_api.h"
#include "common/pg_tde_shmem.h"
#include "storage/lwlock.h"
#include "storage/fd.h"
#include "utils/palloc.h"
#include "utils/memutils.h"
#include "utils/wait_event.h"
#include "common/relpath.h"
#include "miscadmin.h"
#include "funcapi.h"
#include "utils/builtins.h"
#include <sys/time.h>

#define PG_TDE_MASTER_KEY_FILENAME "tde_master_key.info"

static char master_key_info_path[MAXPGPATH] = {0};

typedef struct TdeMasterKeySharedState
{
    LWLock *Lock;
    int hashTrancheId;
    dshash_table_handle hashHandle;
    void *rawDsaArea; /* DSA area pointer */

} TdeMasterKeySharedState;

typedef struct TdeMasterKeylocalState
{
    TdeMasterKeySharedState *sharedMasterKeyState;
    dsa_area *dsa; /* local dsa area for backend attached to the
                    * dsa area created by postmaster at startup.
                    */
    dshash_table *sharedHash;
} TdeMasterKeylocalState;

/* parameter for the master key info shared hash */
static dshash_parameters master_key_dsh_params = {
    sizeof(Oid),
    sizeof(TDEMasterKey),
    dshash_memcmp, /* TODO use int compare instead */
    dshash_memhash};

TdeMasterKeylocalState masterKeyLocalState;

static char *get_master_key_info_path(void);
static void master_key_info_attach_shmem(void);
static Size initialize_shared_state(void *start_address);
static void initialize_objects_in_dsa_area(dsa_area *dsa, void *raw_dsa_area);
static Size cache_area_size(void);
static Size required_shared_mem_size(void);
static void shared_memory_shutdown(int code, Datum arg);

static TDEMasterKeyInfo *save_master_key_info(TDEMasterKey *master_key, GenericKeyring *keyring);
static TDEMasterKeyInfo *get_master_key_info(void);
static inline dshash_table *get_master_key_Hash(void);
static TDEMasterKey *get_master_key_from_cache(void);
static void push_master_key_to_cache(TDEMasterKey *masterKey);
static TDEMasterKey *set_master_key_with_keyring(const char *key_name, GenericKeyring *keyring);

static const TDEShmemSetupRoutine master_key_info_shmem_routine = {
    .init_shared_state = initialize_shared_state,
    .init_dsa_area_objects = initialize_objects_in_dsa_area,
    .required_shared_mem_size = required_shared_mem_size,
    .shmem_kill = shared_memory_shutdown};

void InitializeMasterKeyInfo(void)
{
    ereport(LOG, (errmsg("Initializing TDE master key info")));
    RegisterShmemRequest(&master_key_info_shmem_routine);
}

static Size
cache_area_size(void)
{
    return MAXALIGN(8192 * 100); /* TODO: Probably get it from guc */
}

static Size
required_shared_mem_size(void)
{
    Size sz = cache_area_size();
    sz = add_size(sz, sizeof(TdeMasterKeySharedState));
    return MAXALIGN(sz);
}

/*
 * Initialize the shared area for Master key info.
 * This includes locks and cache area for master key info
 */

static Size
initialize_shared_state(void *start_address)
{
    TdeMasterKeySharedState *sharedState = (TdeMasterKeySharedState *)start_address;
    ereport(LOG, (errmsg("initializing shared state for master key")));
    masterKeyLocalState.dsa = NULL;
    masterKeyLocalState.sharedHash = NULL;

    sharedState->Lock = &(GetNamedLWLockTranche("pg_tde_tranche"))->lock;
    masterKeyLocalState.sharedMasterKeyState = sharedState;
    return sizeof(TdeMasterKeySharedState);
}

void initialize_objects_in_dsa_area(dsa_area *dsa, void *raw_dsa_area)
{
    dshash_table *dsh;
    TdeMasterKeySharedState *sharedState = masterKeyLocalState.sharedMasterKeyState;

    ereport(LOG, (errmsg("initializing dsa area objects for master key")));

    Assert(sharedState != NULL);

    sharedState->rawDsaArea = raw_dsa_area;
    sharedState->hashTrancheId = LWLockNewTrancheId();
    master_key_dsh_params.tranche_id = sharedState->hashTrancheId;
    dsh = dshash_create(dsa, &master_key_dsh_params, 0);
    sharedState->hashHandle = dshash_get_hash_table_handle(dsh);
    dshash_detach(dsh);
}

static void
master_key_info_attach_shmem(void)
{
    MemoryContext oldcontext;

    if (masterKeyLocalState.dsa)
        return;

    /*
     * We want the dsa to remain valid throughout the lifecycle of this
     * process. so switch to TopMemoryContext before attaching
     */
    oldcontext = MemoryContextSwitchTo(TopMemoryContext);

    masterKeyLocalState.dsa = dsa_attach_in_place(masterKeyLocalState.sharedMasterKeyState->rawDsaArea,
                                                  NULL);

    /*
     * pin the attached area to keep the area attached until end of session or
     * explicit detach.
     */
    dsa_pin_mapping(masterKeyLocalState.dsa);

    master_key_dsh_params.tranche_id = masterKeyLocalState.sharedMasterKeyState->hashTrancheId;
    masterKeyLocalState.sharedHash = dshash_attach(masterKeyLocalState.dsa, &master_key_dsh_params,
                                                   masterKeyLocalState.sharedMasterKeyState->hashHandle, 0);
    MemoryContextSwitchTo(oldcontext);
}

static void
shared_memory_shutdown(int code, Datum arg)
{
    masterKeyLocalState.sharedMasterKeyState = NULL;
}

static inline char *
get_master_key_info_path(void)
{
    if (*master_key_info_path == 0)
    {
        snprintf(master_key_info_path, MAXPGPATH, "%s/%s",
                 GetDatabasePath(MyDatabaseId, MyDatabaseTableSpace),
                 PG_TDE_MASTER_KEY_FILENAME);
    }
    return master_key_info_path;
}

static TDEMasterKeyInfo *
save_master_key_info(TDEMasterKey *master_key, GenericKeyring *keyring)
{
    TDEMasterKeyInfo *masterKeyInfo = NULL;
    File master_key_file = -1;
    off_t bytes_written = 0;
    char *info_file_path = get_master_key_info_path();

    Assert(master_key != NULL);
    Assert(keyring != NULL);

    masterKeyInfo = palloc(sizeof(TDEMasterKeyInfo));
    masterKeyInfo->keyId = 0;
    masterKeyInfo->databaseId = MyDatabaseId;
    masterKeyInfo->keyVersion = 1;
    gettimeofday(&masterKeyInfo->creationTime, NULL);
    strncpy(masterKeyInfo->keyName, master_key->keyName, MASTER_KEY_NAME_LEN);
    masterKeyInfo->keyringId = keyring->keyId;

    master_key_file = PathNameOpenFile(info_file_path, O_CREAT | O_EXCL | O_RDWR | PG_BINARY);
    if (master_key_file < 0)
    {
        pfree(masterKeyInfo);
        return NULL;
    }
    bytes_written = FileWrite(master_key_file, masterKeyInfo, sizeof(TDEMasterKeyInfo), 0, WAIT_EVENT_DATA_FILE_WRITE);
    if (bytes_written != sizeof(TDEMasterKeyInfo))
    {
        pfree(masterKeyInfo);
        FileClose(master_key_file);
        /* TODO: delete the invalid file */
        ereport(FATAL,
                (errcode_for_file_access(),
                 errmsg("TDE master key info file \"%s\" can't be written: %m",
                        info_file_path)));
        return NULL;
    }
    FileClose(master_key_file);
    return masterKeyInfo;
}

static TDEMasterKeyInfo *
get_master_key_info(void)
{
    TDEMasterKeyInfo *masterKeyInfo = NULL;
    File master_key_file = -1;
    off_t bytes_read = 0;
    char *info_file_path = get_master_key_info_path();

    /*
     * If file does not exists or does not contain the valid
     * data that means master key does not exists
     */
    master_key_file = PathNameOpenFile(info_file_path, PG_BINARY);
    if (master_key_file < 0)
        return NULL;

    masterKeyInfo = palloc(sizeof(TDEMasterKeyInfo));
    bytes_read = FileRead(master_key_file, masterKeyInfo, sizeof(TDEMasterKeyInfo), 0, WAIT_EVENT_DATA_FILE_READ);
    if (bytes_read == 0)
    {
        pfree(masterKeyInfo);
        return NULL;
    }
    if (bytes_read != sizeof(TDEMasterKeyInfo))
    {
        pfree(masterKeyInfo);
        /* Corrupt file */
        ereport(FATAL,
                (errcode_for_file_access(),
                 errmsg("TDE master key info file \"%s\" is corrupted: %m",
                        info_file_path)));
        return NULL;
    }
    FileClose(master_key_file);
    return masterKeyInfo;
}

/*
 * Public interface to get the master key for the current database
 * If the master key is not present in the cache, it is loaded from
 * the keyring and stored in the cache.
 * When the master key is not set for the database. The function returns
 * throws an error.
 */
TDEMasterKey *
GetMasterKey(void)
{
    TDEMasterKey *masterKey = NULL;
    TDEMasterKeyInfo *masterKeyInfo = NULL;
    GenericKeyring *keyring = NULL;
    const keyInfo *keyInfo = NULL;
    KeyringReturnCodes keyring_ret;

    masterKey = get_master_key_from_cache();
    if (masterKey)
        return masterKey;

    /* Master key not present in cache. Load from the keyring */
    masterKeyInfo = get_master_key_info();
    if (masterKeyInfo == NULL)
    {
        ereport(ERROR,
                (errmsg("Master key does not exists for the database"),
                 errhint("Use set_master_key interface to set the master key")));
        return NULL;
    }

    /* Load the master key from keyring and store it in cache */
    keyring = GetKeyProviderByID(masterKeyInfo->keyringId);
    if (keyring == NULL)
    {
        ereport(ERROR,
                (errmsg("Key provider with ID:\"%d\" does not exists", masterKeyInfo->keyringId)));
        return NULL;
    }

    keyInfo = KeyringGetKey(keyring, masterKeyInfo->keyName, false, &keyring_ret);
    if (keyInfo == NULL)
    {
        ereport(ERROR,
                (errmsg("failed to retrieve master key from keyring")));
        return NULL;
    }

    masterKey = palloc(sizeof(TDEMasterKey));
    masterKey->databaseId = MyDatabaseId;
    masterKey->keyVersion = 1;
    masterKey->keyringId = masterKeyInfo->keyringId;
    strncpy(masterKey->keyName, masterKeyInfo->keyName, TDE_KEY_NAME_LEN);
    masterKey->keyLength = keyInfo->data.len;
    memcpy(masterKey->keyData, keyInfo->data.data, keyInfo->data.len);
    push_master_key_to_cache(masterKey);

    return masterKey;
}

/*
 * SetMasterkey:
 * We need to ensure that only one master key is set for a database.
 * To do that we take a little help from cache. Before setting the
 * master key we take an exclusive lock on the cache entry for the
 * database.
 * After acquiring the exclusive lock we check for the entry again
 * to make sure if some other caller has not added a master key for
 * same database while we were waiting for the lock.
 */

static TDEMasterKey *
set_master_key_with_keyring(const char *key_name, GenericKeyring *keyring)
{
    TDEMasterKey *masterKey = NULL;
    TDEMasterKeyInfo *masterKeyInfo = NULL;
    TdeMasterKeySharedState *shared_state = masterKeyLocalState.sharedMasterKeyState;

    /*
     * Try to get master key from cache. If the cache entry exists
     * throw an error
     * */
    masterKey = get_master_key_from_cache();
    if (masterKey)
    {
        ereport(ERROR,
                (errcode(ERRCODE_DUPLICATE_OBJECT),
                 errmsg("Master key already exists for the database"),
                 errhint("Use rotate_key interface to change the master key")));
        return NULL;
    }
    /* See of valid master key info exists */
    masterKeyInfo = get_master_key_info();
    if (masterKeyInfo)
    {
        ereport(ERROR,
                (errcode(ERRCODE_DUPLICATE_OBJECT),
                 errmsg("Master key already exists for the database"),
                 errhint("Use rotate_key interface to change the master key")));
        return NULL;
    }
    /* Acquire the exclusive lock to disallow concurrent set master key calls */
    LWLockAcquire(shared_state->Lock, LW_EXCLUSIVE);
    /*
     * Make sure just before we got the lock, some other backend
     * has pushed the master key for this database
     */
    masterKey = get_master_key_from_cache();
    if (!masterKey)
    {
        const keyInfo *keyInfo = NULL;
        KeyringReturnCodes keyring_ret;
        masterKey = palloc(sizeof(TDEMasterKey));
        masterKey->databaseId = MyDatabaseId;
        masterKey->keyVersion = 1;
        masterKey->keyringId = keyring->keyId;
        strncpy(masterKey->keyName, key_name, TDE_KEY_NAME_LEN);
        /* We need to get the key from keyring */

        keyInfo = KeyringGetKey(keyring, key_name, false, &keyring_ret);
        if (keyInfo == NULL) /* TODO: check if the key was not present or there was a problem with key provider*/
            keyInfo = keyringGenerateNewKeyAndStore(keyring, key_name, INTERNAL_KEY_LEN, false);

        if (keyInfo == NULL)
        {
            LWLockRelease(shared_state->Lock);
            ereport(ERROR,
                    (errmsg("failed to retrieve master key")));
        }
        masterKey->keyLength = keyInfo->data.len;
        memcpy(masterKey->keyData, keyInfo->data.data, keyInfo->data.len);
        masterKeyInfo = save_master_key_info(masterKey, keyring);
        push_master_key_to_cache(masterKey);
    }
    else
    {
        /*
         * Seems lik just before we got the lock the key was installed by some other caller
         * Throw an error and mover no
         */
        LWLockRelease(shared_state->Lock);
        ereport(ERROR,
            (errcode(ERRCODE_DUPLICATE_OBJECT),
                 errmsg("Master key already exists for the database"),
                 errhint("Use rotate_key interface to change the master key")));
    }

    LWLockRelease(shared_state->Lock);

    return masterKey;
}

TDEMasterKey *
SetMasterKey(const char *key_name, const char *provider_name)
{
    GenericKeyring *keyring = GetKeyProviderByName(provider_name);
    if (keyring == NULL)
    {
        ereport(ERROR,
                (errmsg("Key provider \"%s\" does not exists", provider_name),
                 errhint("Use create_key_provider interface to create the key provider")));
        return NULL;
    }
    return set_master_key_with_keyring(key_name, keyring);
}

/* Master key cache realted stuff */

static inline dshash_table *
get_master_key_Hash(void)
{
    master_key_info_attach_shmem();
    return masterKeyLocalState.sharedHash;
}

/* Gets the master key for current database from cache */
static TDEMasterKey *
get_master_key_from_cache(void)
{
    Oid databaseId = MyDatabaseId;
    TDEMasterKey *cacheEntry = NULL;
    TdeMasterKeySharedState *shared_state = masterKeyLocalState.sharedMasterKeyState;

    /*
     * Acquire a shared lock to make sure key roatation is not in progress
     */
    LWLockAcquire(shared_state->Lock, LW_SHARED);

    cacheEntry = (TDEMasterKey *)dshash_find(get_master_key_Hash(),
                                             &databaseId, false);
    if (cacheEntry)
        dshash_release_lock(get_master_key_Hash(), cacheEntry);
    LWLockRelease(shared_state->Lock);
    return cacheEntry;
}

/* Gets the master key for current database from cache */
static void
push_master_key_to_cache(TDEMasterKey *masterKey)
{
    TDEMasterKey *cacheEntry = NULL;
    Oid databaseId = MyDatabaseId;
    bool found = false;
    cacheEntry = dshash_find_or_insert(get_master_key_Hash(),
                                       &databaseId, &found);
    if (!found)
        memcpy(cacheEntry, masterKey, sizeof(TDEMasterKey));
    dshash_release_lock(get_master_key_Hash(), cacheEntry);
}

/* SQL interface to set master key */
PG_FUNCTION_INFO_V1(pg_tde_set_master_key);
Datum pg_tde_set_master_key(PG_FUNCTION_ARGS);

Datum pg_tde_set_master_key(PG_FUNCTION_ARGS)
{
    char *master_key_name = text_to_cstring(PG_GETARG_TEXT_PP(0));
    char *provider_name = text_to_cstring(PG_GETARG_TEXT_PP(1));

    ereport(LOG, (errmsg("Setting master key [%s : %s] for the database", master_key_name, provider_name)));
    SetMasterKey(master_key_name, provider_name);
    PG_RETURN_NULL();
}
