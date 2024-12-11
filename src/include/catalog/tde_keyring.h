/*-------------------------------------------------------------------------
 *
 * tde_keyring.h
 *	  TDE catalog handling
 *
 * src/include/catalog/tde_keyring.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef TDE_KEYRING_H
#define TDE_KEYRING_H

#include "postgres.h"
#include "nodes/pg_list.h"
#include "catalog/keyring_min.h"

#define PG_TDE_NAMESPACE_NAME "percona_tde"
#define PG_TDE_KEY_PROVIDER_CAT_NAME "pg_tde_key_provider"

/* This record goes into key provider info file */
typedef struct KeyringProvideRecord
{
	int	provider_id;
	char provider_name[MAX_PROVIDER_NAME_LEN];
	char options[MAX_KEYRING_OPTION_LEN];
	ProviderType provider_type;
} KeyringProvideRecord;
typedef struct KeyringProviderXLRecord
{
	Oid	database_id;
	off_t offset_in_file;
	KeyringProvideRecord provider;
} KeyringProviderXLRecord;

extern List *GetAllKeyringProviders(Oid dbOid);
extern GenericKeyring *GetKeyProviderByName(const char *provider_name, Oid dbOid);
extern GenericKeyring *GetKeyProviderByID(int provider_id, Oid dbOid);
extern ProviderType get_keyring_provider_from_typename(char *provider_type);
extern void cleanup_key_provider_info(Oid databaseId);
extern void InitializeKeyProviderInfo(void);
extern uint32 save_new_key_provider_info(KeyringProvideRecord *provider, 
											Oid databaseId, bool write_xlog);
extern uint32 redo_key_provider_info(KeyringProviderXLRecord *xlrec);

extern bool ParseKeyringJSONOptions(ProviderType provider_type, void *out_opts,
									char *in_buf, int buf_len);
#endif /* TDE_KEYRING_H */
