
#include "smgr/pg_tde_smgr.h"
#include "postgres.h"
#include "storage/smgr.h"
#include "storage/md.h"
#include "catalog/catalog.h"
#include "encryption/enc_aes.h"
#include "access/pg_tde_tdemap.h"
#include "pg_tde_event_capture.h"

#ifdef PERCONA_FORK

// TODO: implement proper IV
// iv should be based on blocknum + relfile, available in the API
static unsigned char iv[16] = {0,};

static RelKeyData*
tde_smgr_get_key(SMgrRelation reln)
{
	// TODO: This recursion counter is a dirty hack until the metadata is in the catalog
	// As otherwise we would call GetPrincipalKey recursively and deadlock
	static int recursion = 0;
	TdeCreateEvent *event;
	RelKeyData *rkd;

	if(IsCatalogRelationOid(reln->smgr_rlocator.locator.relNumber))
	{
		// do not try to encrypt/decrypt catalog tables
		return NULL;
	}

	if(recursion != 0) 
	{
		return NULL;
	}

	recursion++;

	if(GetPrincipalKey(reln->smgr_rlocator.locator.dbOid, reln->smgr_rlocator.locator.spcOid)==NULL)
	{
		recursion--;
		return NULL;
	}

	event = GetCurrentTdeCreateEvent();

	// see if we have a key for the relation, and return if yes
	rkd = GetRelationKey(reln->smgr_rlocator.locator);

	if(rkd != NULL)
	{
		recursion--;
		return rkd;
	}

	// if this is a CREATE TABLE, we have to generate the key
	if(event->encryptMode == true && event->eventType == TDE_TABLE_CREATE_EVENT)
	{
		recursion--;
		return pg_tde_create_key_map_entry(&reln->smgr_rlocator.locator);
	}
	
	// if this is a CREATE INDEX, we have to load the key based on the table
	if(event->encryptMode == true && event->eventType == TDE_INDEX_CREATE_EVENT)
	{
		// For now keep it simple and create separate key for indexes
		// Later we might modify the map infrastructure to support the same keys
		recursion--;
		return pg_tde_create_key_map_entry(&reln->smgr_rlocator.locator);
	}

	recursion--;

	return NULL;
}

static void
tde_mdwritev(SMgrRelation reln, ForkNumber forknum, BlockNumber blocknum,
		 const void **buffers, BlockNumber nblocks, bool skipFsync)
{
	AesInit();

	RelKeyData* rkd = tde_smgr_get_key(reln);

	if(rkd == NULL)
	{
		mdwritev(reln, forknum, blocknum, buffers, nblocks, skipFsync);

		return;
	}
	else
	{
		char *local_blocks = palloc(BLCKSZ * (nblocks + 1));
		char *local_blocks_aligned = (char *)TYPEALIGN(PG_IO_ALIGN_SIZE, local_blocks);
		const void **local_buffers = palloc(sizeof(void *) * nblocks);

		for(int i = 0; i  < nblocks; ++i )
		{
			int out_len = BLCKSZ;
			local_buffers[i] = &local_blocks_aligned[i * BLCKSZ];
			AesEncrypt(rkd->internal_key.key, iv, ((char**)buffers)[i], BLCKSZ, local_buffers[i], &out_len);
		}

		mdwritev(reln, forknum, blocknum,
			local_buffers, nblocks, skipFsync);

		pfree(local_blocks);
		pfree(local_buffers);
	}
}

static void
tde_mdextend(SMgrRelation reln, ForkNumber forknum, BlockNumber blocknum,
		 const void *buffer, bool skipFsync)
{
	RelKeyData *rkd;

	AesInit();

	rkd = tde_smgr_get_key(reln);

	if(rkd == NULL)
	{
		mdextend(reln, forknum, blocknum, buffer, skipFsync);

		return;
	}
	else
	{

		char *local_blocks = palloc(BLCKSZ * (1 + 1));
		char *local_blocks_aligned = (char *)TYPEALIGN(PG_IO_ALIGN_SIZE, local_blocks);
		int out_len = BLCKSZ;
		AesEncrypt(rkd->internal_key.key, iv, ((char*)buffer), BLCKSZ, local_blocks_aligned, &out_len);

		mdextend(reln, forknum, blocknum, local_blocks_aligned, skipFsync);

		pfree(local_blocks);
	}
}

static void
tde_mdreadv(SMgrRelation reln, ForkNumber forknum, BlockNumber blocknum,
		void **buffers, BlockNumber nblocks)
{
	RelKeyData *rkd;
	int out_len = BLCKSZ;

	AesInit();

	mdreadv(reln, forknum, blocknum, buffers, nblocks);

	rkd = tde_smgr_get_key(reln);

	if(rkd == NULL)
		return;

	for(int i = 0; i < nblocks; ++i)
	{
		bool allZero = true;
		for(int j = 0; j  < 32; ++j)
		{
			if(((char**)buffers)[i][j] != 0)
			{
				// Postgres creates all zero blocks in an optimized route, which we do not try
				// to encrypt.
				// Instead we detect if a block is all zero at decryption time, and
				// leave it as is.
				// This could be a security issue later, but it is a good first prototype
				allZero = false;
				break;
			}
		}
		if(allZero)
			continue;
		AesDecrypt(rkd->internal_key.key, iv, ((char **)buffers)[i], BLCKSZ, ((char **)buffers)[i], &out_len);
	}
}

static void
tde_mdcreate(SMgrRelation reln, ForkNumber forknum, bool isRedo)
{
	// This is the only function that gets called during actual CREATE TABLE/INDEX (EVENT TRIGGER)
	// so we create the key here by loading it
	// Later calls then decide to encrypt or not based on the existence of the key
	tde_smgr_get_key(reln);
	return mdcreate(reln, forknum, isRedo);
}


static SMgrId tde_smgr_id;
static const struct f_smgr tde_smgr = {
	.name = "tde",
	.smgr_init = mdinit,
	.smgr_shutdown = NULL,
	.smgr_open = mdopen,
	.smgr_close = mdclose,
	.smgr_create = tde_mdcreate,
	.smgr_exists = mdexists,
	.smgr_unlink = mdunlink,
	.smgr_extend = tde_mdextend,
	.smgr_zeroextend = mdzeroextend,
	.smgr_prefetch = mdprefetch,
	.smgr_readv = tde_mdreadv,
	.smgr_writev = tde_mdwritev,
	.smgr_writeback = mdwriteback,
	.smgr_nblocks = mdnblocks,
	.smgr_truncate = mdtruncate,
	.smgr_immedsync = mdimmedsync,
	.smgr_registersync = mdregistersync,
};

void RegisterStorageMgr(void)
{
    tde_smgr_id = smgr_register(&tde_smgr, 0);

	// TODO: figure out how this part should work in a real extension
	storage_manager_id = tde_smgr_id; 
}

#else
void RegisterStorageMgr(void)
{
}
#endif /* PERCONA_FORK */
