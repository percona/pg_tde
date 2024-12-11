
#ifndef KEYRING_MIN_H_
#define KEYRING_MIN_H_

#include "pg_config_manual.h"

/* This is a minimal header that doesn't depend on postgres headers to avoid a type conflict with libkmip */

typedef unsigned int Oid;

#define MAX_PROVIDER_NAME_LEN 128 /* pg_tde_key_provider's provider_name size*/
#define MAX_VAULT_V2_KEY_LEN 128  /* From hashi corp docs */
#define MAX_KEYRING_OPTION_LEN 1024
typedef enum ProviderType
{
    UNKNOWN_KEY_PROVIDER,
    FILE_KEY_PROVIDER,
    VAULT_V2_KEY_PROVIDER,
    KMIP_KEY_PROVIDER,
} ProviderType;

#define TDE_KEY_NAME_LEN 256
#define MAX_KEY_DATA_SIZE 32	/* maximum 256 bit encryption */
#define INTERNAL_KEY_LEN 16

typedef struct keyName
{
	char name[TDE_KEY_NAME_LEN];
} keyName;

typedef struct keyData
{
	unsigned char data[MAX_KEY_DATA_SIZE];
	unsigned len;
} keyData;

typedef struct keyInfo
{
	keyName	name;
	keyData	data;
} keyInfo;

typedef enum KeyringReturnCodes
{
	KEYRING_CODE_SUCCESS = 0,
	KEYRING_CODE_INVALID_PROVIDER,
	KEYRING_CODE_RESOURCE_NOT_AVAILABLE,
	KEYRING_CODE_RESOURCE_NOT_ACCESSABLE,
	KEYRING_CODE_INVALID_OPERATION,
	KEYRING_CODE_INVALID_RESPONSE,
	KEYRING_CODE_INVALID_KEY_SIZE,
	KEYRING_CODE_DATA_CORRUPTED
} KeyringReturnCodes;

/* Base type for all keyring */
typedef struct GenericKeyring
{
    ProviderType type; /* Must be the first field */
    Oid key_id;
    char provider_name[MAX_PROVIDER_NAME_LEN];
    char options[MAX_KEYRING_OPTION_LEN]; /* User provided options string*/
} GenericKeyring;

typedef struct TDEKeyringRoutine
{
	keyInfo    *(*keyring_get_key) (GenericKeyring *keyring, const char *key_name, bool throw_error, KeyringReturnCodes * returnCode);
				KeyringReturnCodes(*keyring_store_key) (GenericKeyring *keyring, keyInfo *key, bool throw_error);
} TDEKeyringRoutine;

/*
 * Keyring type name must be in sync with catalog table
 * defination in pg_tde--1.0 SQL
 */
#define FILE_KEYRING_TYPE "file"
#define VAULTV2_KEYRING_TYPE "vault-v2"
#define KMIP_KEYRING_TYPE "kmip"

typedef struct FileKeyring
{
    GenericKeyring keyring; /* Must be the first field */
    char file_name[MAXPGPATH];
} FileKeyring;

typedef struct VaultV2Keyring
{
    GenericKeyring keyring; /* Must be the first field */
    char vault_token[MAX_VAULT_V2_KEY_LEN];
    char vault_url[MAXPGPATH];
    char vault_ca_path[MAXPGPATH];
    char vault_mount_path[MAXPGPATH];
} VaultV2Keyring;

typedef struct KmipKeyring
{
    GenericKeyring keyring; /* Must be the first field */
    char kmip_host[MAXPGPATH];
    char kmip_port[32];
    char kmip_ca_path[MAXPGPATH];
    char kmip_cert_path[MAXPGPATH];
} KmipKeyring;

#endif