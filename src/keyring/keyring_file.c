/*
 * Implements the file provider keyring routines.
 */

#include "postgres.h"

#include "common/file_perm.h"
#include "storage/fd.h"
#include "utils/wait_event.h"

#include "catalog/tde_keyring.h"
#include "keyring/keyring_api.h"
#include "keyring/keyring_file.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

static KeyInfo *get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code);
static void set_key_by_name(GenericKeyring *keyring, KeyInfo *key);
static void validate(GenericKeyring *keyring);

static const TDEKeyringRoutine keyringFileRoutine = {
	.keyring_get_key = get_key_by_name,
	.keyring_store_key = set_key_by_name,
	.keyring_validate = validate,
};

void
InstallFileKeyring(void)
{
	RegisterKeyProviderType(&keyringFileRoutine, FILE_KEY_PROVIDER);
}

static KeyInfo *
get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code)
{
	KeyInfo    *key = NULL;
	int			fd = -1;
	FileKeyring *file_keyring = (FileKeyring *) keyring;
	off_t		bytes_read = 0;
	off_t		curr_pos = 0;

	*return_code = KEYRING_CODE_SUCCESS;

	fd = OpenTransientFile(file_keyring->file_name, PG_BINARY);
	if (fd < 0)
		return NULL;

	key = palloc_object(KeyInfo);
	while (true)
	{
		bytes_read = pg_pread(fd, key, sizeof(KeyInfo), curr_pos);
		curr_pos += bytes_read;

		if (bytes_read == 0)
		{
			/*
			 * Empty keyring file is considered as a valid keyring file that
			 * has no keys
			 */
			CloseTransientFile(fd);
			pfree(key);
			return NULL;
		}
		if (bytes_read != sizeof(KeyInfo))
		{
			CloseTransientFile(fd);
			pfree(key);
			/* Corrupt file */
			*return_code = KEYRING_CODE_DATA_CORRUPTED;
			ereport(WARNING,
					errcode_for_file_access(),
					errmsg("keyring file \"%s\" is corrupted: %m",
						   file_keyring->file_name),
					errdetail("invalid key size %lu expected %lu", bytes_read, sizeof(KeyInfo)));
			return NULL;
		}
		if (strncasecmp(key->name, key_name, sizeof(key->name)) == 0)
		{
			CloseTransientFile(fd);
			return key;
		}
	}
	CloseTransientFile(fd);
	pfree(key);
	return NULL;
}

static void
set_key_by_name(GenericKeyring *keyring, KeyInfo *key)
{
	off_t		bytes_written = 0;
	off_t		curr_pos = 0;
	int			fd;
	FileKeyring *file_keyring = (FileKeyring *) keyring;
	KeyInfo    *existing_key;
	KeyringReturnCode return_code = KEYRING_CODE_SUCCESS;

	Assert(key != NULL);
	/* See if the key with same name already exists */
	existing_key = get_key_by_name(keyring, key->name, &return_code);
	if (existing_key)
	{
		ereport(ERROR,
				errmsg("Key with name %s already exists in keyring", key->name));
	}

	fd = OpenTransientFile(file_keyring->file_name, O_CREAT | O_RDWR | PG_BINARY);
	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("Failed to open keyring file %s: %m", file_keyring->file_name));
	}
	/* Write key to the end of file */
	curr_pos = lseek(fd, 0, SEEK_END);
	bytes_written = pg_pwrite(fd, key, sizeof(KeyInfo), curr_pos);
	if (bytes_written != sizeof(KeyInfo))
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("keyring file \"%s\" can't be written: %m",
					   file_keyring->file_name));
	}

	if (pg_fsync(fd) != 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not fsync file \"%s\": %m",
					   file_keyring->file_name));
	}
	CloseTransientFile(fd);
}

static void
validate(GenericKeyring *keyring)
{
	FileKeyring *file_keyring = (FileKeyring *) keyring;
	int			fd = OpenTransientFile(file_keyring->file_name, O_CREAT | O_RDWR | PG_BINARY);

	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("Failed to open keyring file %s: %m", file_keyring->file_name));
	}

	CloseTransientFile(fd);
}
