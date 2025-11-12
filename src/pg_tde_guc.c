/*
 * GUC variables for pg_tde
 */

#include "postgres.h"

#include "utils/guc.h"

#include "encryption/enc_tde.h"
#include "keyring/keyring_api.h"
#include "pg_tde_guc.h"

bool		AllowInheritGlobalProviders = true;
bool		EncryptXLog = false;
bool		EnforceEncryption = false;
int			Cipher = CIPHER_AES_128;
int			KeyLength = KEY_DATA_SIZE_128;

/* Custom GUC variable */
static const struct config_enum_entry cipher_options[] = {
	{"aes_128", CIPHER_AES_128, false},
	{"aes_256", CIPHER_AES_256, false},
	{NULL, 0, false}
};

static void
assign_keys_size(int newval, void *extra)
{
	KeyLength = pg_tde_cipher_key_length(newval);
}

void
TdeGucInit(void)
{
	DefineCustomBoolVariable("pg_tde.inherit_global_providers", /* name */
							 "Allow using global key providers for databases.", /* short_desc */
							 NULL,	/* long_desc */
							 &AllowInheritGlobalProviders,	/* value address */
							 true,	/* boot value */
							 PGC_SUSET, /* context */
							 0, /* flags */
							 NULL,	/* check_hook */
							 NULL,	/* assign_hook */
							 NULL	/* show_hook */
		);

	DefineCustomBoolVariable("pg_tde.wal_encrypt",	/* name */
							 "Enable/Disable encryption of WAL.",	/* short_desc */
							 NULL,	/* long_desc */
							 &EncryptXLog,	/* value address */
							 false, /* boot value */
							 PGC_POSTMASTER,	/* context */
							 0, /* flags */
							 NULL,	/* check_hook */
							 NULL,	/* assign_hook */
							 NULL	/* show_hook */
		);

	DefineCustomBoolVariable("pg_tde.enforce_encryption",	/* name */
							 "Only allow the creation of encrypted tables.",	/* short_desc */
							 NULL,	/* long_desc */
							 &EnforceEncryption,	/* value address */
							 false, /* boot value */
							 PGC_SUSET, /* context */
							 0, /* flags */
							 NULL,	/* check_hook */
							 NULL,	/* assign_hook */
							 NULL	/* show_hook */
		);

	DefineCustomEnumVariable("pg_tde.cipher",	/* name */
							 "TDE encryption algorithm.",	/* short_desc */
							 NULL,	/* long_desc */
							 &Cipher,	/* value address */
							 CIPHER_AES_128,	/* boot value */
							 cipher_options,	/* options */
							 PGC_SUSET, /* context */
							 0, /* flags */
							 NULL,	/* check_hook */
							 assign_keys_size,	/* assign_hook */
							 NULL	/* show_hook */
		);

}
