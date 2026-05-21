#include "postgres_fe.h"

#include "pg_tde_fe.h"
#include "common/pg_tde_utils.h"
#include "encryption/enc_aes.h"
#include "keyring/keyring_file.h"
#include "keyring/keyring_vault.h"
#include "keyring/keyring_kmip.h"

/* Frontend has to call this to access keys */
void
pg_tde_fe_init(const char *kring_dir)
{
	AesInit();
	InstallFileKeyring();
	InstallVaultV2Keyring();
	InstallKmipKeyring();
	pg_tde_set_data_dir(kring_dir);
}
