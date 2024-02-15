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


#define PG_TDE_NAMESPACE_NAME			"percona_tde"
#define PG_TDE_KEY_PROVIDER_CAT_NAME	"pg_tde_key_provider"

#define FILE_KEYRING_TYPE 			"file"
#define VALUTV2_KEYRING_TYPE 		"vault-v2"

typedef enum ProviderType
{
	UNKNOWN_KEY_PROVIDER,
	FILE_KEY_PROVIDER,
	VAULT_V2_KEY_PROVIDER,
} ProviderType;

/* Base type for all keyring */
typedef struct GenericKeyring
{
	ProviderType type;	/* Must be the first field */
	Oid keyId;
	char keyName[128];
}GenericKeyring;

typedef struct FileKeyring
{
	GenericKeyring keyring;	/* Must be the first field */
	char file_name[MAXPGPATH];
} FileKeyring;

typedef struct ValutV2Keyring
{
	GenericKeyring keyring;	/* Must be the first field */
	char vault_token[128];
	char vault_url[MAXPGPATH];
	char vault_ca_path[MAXPGPATH];
	char vault_mount_path[MAXPGPATH];
} ValutV2Keyring;

extern List* GetAllKeyringProviders(void);
extern GenericKeyring* GetKeyProviderByName(const char *provider_name);
extern GenericKeyring* GetKeyProviderByID(int provider_id);

#endif /*TDE_KEYRING_H*/
