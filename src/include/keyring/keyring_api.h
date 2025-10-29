#ifndef KEYRING_API_H
#define KEYRING_API_H

#define MAX_PROVIDER_NAME_LEN 128	/* pg_tde_key_provider's provider_name
									 * size */
#define MAX_KEYRING_OPTION_LEN 1024

typedef enum ProviderType
{
	UNKNOWN_KEY_PROVIDER,
	FILE_KEY_PROVIDER,
	VAULT_V2_KEY_PROVIDER,
	KMIP_KEY_PROVIDER,
} ProviderType;

#define TDE_KEY_NAME_LEN 256
#define KEY_DATA_SIZE_128 16	/* 128 bit encryption */
#define KEY_DATA_SIZE_256 32	/* 256 bit encryption, not yet supported */
#define MAX_KEY_DATA_SIZE KEY_DATA_SIZE_256 /* maximum 256 bit encryption */

typedef struct KeyData
{
	unsigned char data[MAX_KEY_DATA_SIZE];
	unsigned	len;
} KeyData;

typedef struct KeyInfo
{
	char		name[TDE_KEY_NAME_LEN];
	KeyData		data;
} KeyInfo;

typedef enum KeyringReturnCode
{
	KEYRING_CODE_SUCCESS = 0,
	KEYRING_CODE_INVALID_PROVIDER = 1,
	KEYRING_CODE_RESOURCE_NOT_AVAILABLE = 2,
	KEYRING_CODE_INVALID_RESPONSE = 5,
	KEYRING_CODE_INVALID_KEY = 6,
	KEYRING_CODE_DATA_CORRUPTED = 7,
} KeyringReturnCode;

/* Base type for all keyring */
typedef struct GenericKeyring
{
	ProviderType type;			/* Must be the first field */
	int			keyring_id;
	char		provider_name[MAX_PROVIDER_NAME_LEN];
	char		options[MAX_KEYRING_OPTION_LEN];	/* User provided options
													 * string */
} GenericKeyring;

typedef struct TDEKeyringRoutine
{
	KeyInfo    *(*keyring_get_key) (GenericKeyring *keyring, const char *key_name, KeyringReturnCode *returnCode);
	void		(*keyring_store_key) (GenericKeyring *keyring, KeyInfo *key);
	void		(*keyring_validate) (GenericKeyring *keyring);
} TDEKeyringRoutine;

typedef struct FileKeyring
{
	GenericKeyring keyring;		/* Must be the first field */
	char	   *file_name;
} FileKeyring;

typedef struct VaultV2Keyring
{
	GenericKeyring keyring;		/* Must be the first field */
	char	   *vault_token;
	char	   *vault_token_path;
	char	   *vault_url;
	char	   *vault_ca_path;
	char	   *vault_mount_path;
	char	   *vault_namespace;
} VaultV2Keyring;

typedef struct KmipKeyring
{
	GenericKeyring keyring;		/* Must be the first field */
	char	   *kmip_host;
	char	   *kmip_port;
	char	   *kmip_ca_path;
	char	   *kmip_cert_path;
	char	   *kmip_key_path;
} KmipKeyring;

extern void RegisterKeyProviderType(const TDEKeyringRoutine *routine, ProviderType type);

extern KeyInfo *KeyringGetKey(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *returnCode);
extern KeyInfo *KeyringGenerateNewKeyAndStore(GenericKeyring *keyring, const char *key_name, unsigned key_len);
extern void KeyringValidate(GenericKeyring *keyring);
extern bool ValidateKey(KeyInfo *key);
extern char *KeyringErrorCodeToString(KeyringReturnCode code);

#endif							/* KEYRING_API_H */
