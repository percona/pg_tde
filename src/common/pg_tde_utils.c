#include "postgres.h"

#include "access/pg_tde_xlog_keys.h"
#include "catalog/tde_principal_key.h"
#include "common/pg_tde_utils.h"
#include "pg_tde.h"

#ifndef FRONTEND
#include "access/relation.h"
#include "fmgr.h"
#include "utils/rel.h"
#include "smgr/pg_tde_smgr.h"

PG_FUNCTION_INFO_V1(pg_tde_is_encrypted);
Datum
pg_tde_is_encrypted(PG_FUNCTION_ARGS)
{
	Oid			relationOid = PG_GETARG_OID(0);
	LOCKMODE	lockmode = AccessShareLock;
	Relation	rel = relation_open(relationOid, lockmode);
	bool		result;

	if (!RELKIND_HAS_STORAGE(rel->rd_rel->relkind))
	{
		relation_close(rel, lockmode);
		PG_RETURN_NULL();
	}

	if (RELATION_IS_OTHER_TEMP(rel))
		ereport(ERROR,
				errcode(ERRCODE_FEATURE_NOT_SUPPORTED),
				errmsg("we cannot check if temporary relations from other backends are encrypted"));

	result = tde_smgr_rel_is_encrypted(RelationGetSmgr(rel));

	relation_close(rel, lockmode);

	PG_RETURN_BOOL(result);
}

#endif							/* !FRONTEND */

static char tde_data_dir[MAXPGPATH] = PG_TDE_DATA_DIR;
static char wal_key_file_path[MAXPGPATH] = "";


#ifdef FRONTEND
/*
 * Changes TDE data dir (keys location) and resets necessary caches.
 *
 * Currently, only frontend tools can change this. For backend it is always
 * in PGDATA.
 */
void
pg_tde_set_data_dir(const char *dir)
{
	Assert(dir != NULL);

	strlcpy(tde_data_dir, dir, sizeof(tde_data_dir));

	snprintf(wal_key_file_path, MAXPGPATH, "%s/" PG_TDE_WAL_KEY_FILE_NAME, tde_data_dir);

	/* New dir, new keys. Reset caches */
	pg_tde_free_wal_key_cache();
	clean_fe_server_principal_key_cache();
}
#endif

const char *
pg_tde_get_data_dir(void)
{
	return tde_data_dir;
}

const char *
get_wal_key_file_path(void)
{
	if (strlen(wal_key_file_path) == 0)
		snprintf(wal_key_file_path, MAXPGPATH, "%s/" PG_TDE_WAL_KEY_FILE_NAME, tde_data_dir);

	return wal_key_file_path;
}
