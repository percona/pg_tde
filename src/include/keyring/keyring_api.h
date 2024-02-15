/*-------------------------------------------------------------------------
 *
 * keyring_api.h
 * src/include/keyring/keyring_api.h
 *
 *-------------------------------------------------------------------------
 */

#ifndef KEYRING_API_H
#define KEYRING_API_H

#include "catalog/tde_keyring.h"


typedef struct keyName
{
	char name[256]; // enough for now
} keyName;

typedef struct keyData
{
	unsigned char data[32]; // maximum 256 bit encryption
	unsigned len;
} keyData;

typedef struct keyInfo
{
	keyName name;
	keyData data;
} keyInfo;

typedef enum KeyringReturnCodes
{
	KEYRING_CODE_SUCCESS = 0,
	KEYRING_CODE_INVALID_PROVIDER,
	KEYRING_CODE_RESOURCE_NOT_AVAILABLE,
	KEYRING_CODE_RESOURCE_NOT_ACCESSABLE,
	KEYRING_CODE_DATA_CORRUPTED
} KeyringReturnCodes;

typedef struct TDEKeyringRoutine
{
    keyInfo* (*keyring_get_key)(GenericKeyring* keyring, const char* key_name, bool throw_error, KeyringReturnCodes *returnCode);
    KeyringReturnCodes (*keyring_store_key)(GenericKeyring* keyring, keyInfo *key, bool throw_error);
}TDEKeyringRoutine;

extern bool RegisterKeyProvider(const TDEKeyringRoutine* routine, ProviderType type);

extern KeyringReturnCodes KeyringStoreKey(GenericKeyring* keyring, keyInfo *key, bool throw_error);
extern keyInfo* KeyringGetKey(GenericKeyring* keyring, const char* key_name, bool throw_error, KeyringReturnCodes *returnCode);

extern keyInfo* keyringGenerateNewKeyAndStore(GenericKeyring* keyring, const char* key_name, unsigned key_len, bool throw_error);
extern keyInfo* keyringGenerateNewKey(const char* key_name, unsigned key_len);

// TODO: this type should be hidden in the C file
#define MAX_CACHE_ENTRIES 1024
typedef struct keyringCache
{
	keyInfo keys[MAX_CACHE_ENTRIES];
	unsigned keyCount;
} keyringCache;


// Keys are named in the following format: <internalName>-<version>-<serverID>

// Returned keyInfo struts are all referenced to the internal key cache

// Functions that work with internal names and versions
keyName keyringConstructKeyName(const char* internalName, unsigned version); // returns palloc

// Generates next available version with the given internalName
// We assume that there are no gaps in the version sequence!
const keyInfo* keyringGenerateKey(const char* internalName, unsigned keyLen);

// Functions that work on full key names
const keyInfo* keyringGetKey(keyName name);
const keyInfo* keyringStoreKey(keyName name, keyData data);

const char * tde_sprint_masterkey(const keyData *k);

#endif // KEYRING_API_H
