/*-------------------------------------------------------------------------
 *
 * tde_master_key.h
 *	  TDE master key handling
 *
 * src/include/catalog/tde_master_key.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef TDE_MASTER_KEY_H
#define TDE_MASTER_KEY_H


#include "postgres.h"
#include "catalog/tde_keyring.h"
#include "nodes/pg_list.h"


#define TDE_MASTER_KEY_LEN	255
#define MAX_KEY_DATA_SIZE   32 /* maximum 256 bit encryption */
#define MASTER_KEY_LEN 		16

typedef struct TDEMasterKey
{
	Oid databaseId;
	uint32 keyVersion;
    Oid keyringId;
	char keyName[TDE_MASTER_KEY_LEN];
	unsigned char keyData[MAX_KEY_DATA_SIZE];
	uint32 keyLength;
} TDEMasterKey;


typedef struct TDEMasterKeyInfo
{
	Oid keyId;
    Oid keyringId;
	Oid databaseId;
    Oid userId;
    struct timeval creationTime;
	int keyVersion;
	char keyName[TDE_MASTER_KEY_LEN];
} TDEMasterKeyInfo;

extern void InitializeMasterKeyInfo(void);
extern TDEMasterKey* GetMasterKey(void);
TDEMasterKey* SetMasterKey(const char* key_name, const char* provider_name);
#endif /*TDE_MASTER_KEY_H*/
