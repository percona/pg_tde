/*-------------------------------------------------------------------------
 *
 * tde_principal_key.h
 *	  TDE principal key handling
 *
 * src/include/catalog/tde_principal_key.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef PG_TDE_PRINCIPAL_KEY_H
#define PG_TDE_PRINCIPAL_KEY_H


#include "postgres.h"
#include "catalog/tde_keyring.h"
#include "keyring/keyring_api.h"
#include "nodes/pg_list.h"
#ifndef FRONTEND
#include "storage/lwlock.h"
#endif

#define DEFAULT_PRINCIPAL_KEY_VERSION      1
#define PRINCIPAL_KEY_NAME_LEN TDE_KEY_NAME_LEN
#define MAX_PRINCIPAL_KEY_VERSION_NUM 100000

typedef struct TDEPrincipalKeyId
{
	uint32		version;
	char		name[PRINCIPAL_KEY_NAME_LEN];
	char		versioned_name[PRINCIPAL_KEY_NAME_LEN + 4];
} TDEPrincipalKeyId;

typedef struct TDEPrincipalKeyInfo
{
	Oid			databaseId;
	Oid			tablespaceId;
	Oid			userId;
	Oid			keyringId;
	struct timeval creationTime;
	TDEPrincipalKeyId keyId;
} TDEPrincipalKeyInfo;

typedef struct TDEPrincipalKey
{
	TDEPrincipalKeyInfo keyInfo;
	unsigned char keyData[MAX_KEY_DATA_SIZE];
	uint32		keyLength;
} TDEPrincipalKey;

typedef struct XLogPrincipalKeyRotate
{
	Oid			databaseId;
	off_t		map_size;
	off_t		keydata_size;
	char		buff[FLEXIBLE_ARRAY_MEMBER];
} XLogPrincipalKeyRotate;

#define SizeoOfXLogPrincipalKeyRotate	offsetof(XLogPrincipalKeyRotate, buff)

extern void InitializePrincipalKeyInfo(void);
extern void cleanup_principal_key_info(Oid databaseId, Oid tablespaceId);

#ifndef FRONTEND
extern LWLock *tde_lwlock_enc_keys(void);
extern TDEPrincipalKey *GetPrincipalKey(Oid dbOid, Oid spcOid, LWLockMode lockMode);
#else
extern TDEPrincipalKey *GetPrincipalKey(Oid dbOid, Oid spcOid, void *lockMode);
#endif

extern bool save_principal_key_info(TDEPrincipalKeyInfo *principalKeyInfo);

extern Oid	GetPrincipalKeyProviderId(void);
extern bool SetPrincipalKey(const char *key_name, const char *provider_name, bool ensure_new_key);
extern bool RotatePrincipalKey(TDEPrincipalKey *current_key, const char *new_key_name, const char *new_provider_name, bool ensure_new_key);
extern bool xl_tde_perform_rotate_key(XLogPrincipalKeyRotate *xlrec);

#endif							/* PG_TDE_PRINCIPAL_KEY_H */
