/*
 * Implements the file provider keyring routines.
 */

#include "postgres.h"

#include <unistd.h>

#include "common/file_perm.h"
#include "storage/fd.h"
#include "utils/wait_event.h"

#include "catalog/tde_keyring.h"
#include "keyring/keyring_api.h"
#include "keyring/keyring_file.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

typedef struct
{
	char		name[TDE_KEY_NAME_LEN];
	KeyData		key;
} KeyRecord;

static KeyData *get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code);
static void set_key_by_name(GenericKeyring *keyring, const char *key_name, KeyData *key);
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

static KeyData *
get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code)
{
	KeyRecord	record;
	int			fd = -1;
	FileKeyring *file_keyring = (FileKeyring *) keyring;
	off_t		bytes_read = 0;
	off_t		curr_pos = 0;

	*return_code = KEYRING_CODE_SUCCESS;

	fd = OpenTransientFile(file_keyring->file_name, PG_BINARY);
	if (fd < 0)
		return NULL;

	while (true)
	{
		bytes_read = pg_pread(fd, &record, sizeof(record), curr_pos);
		curr_pos += bytes_read;

		if (bytes_read == 0)
		{
			/*
			 * Empty keyring file is considered as a valid keyring file that
			 * has no keys
			 */
			CloseTransientFile(fd);
			return NULL;
		}
		if (bytes_read != sizeof(record))
		{
			CloseTransientFile(fd);
			/* Corrupt file */
			*return_code = KEYRING_CODE_DATA_CORRUPTED;
			ereport(WARNING,
					errcode_for_file_access(),
					errmsg("keyring file \"%s\" is corrupted: %m",
						   file_keyring->file_name),
					errdetail("invalid key size %lld expected %lu",
							  (long long int) bytes_read, sizeof(record)));
			return NULL;
		}
		if (pg_strncasecmp(record.name, key_name, sizeof(record.name)) == 0)
		{
			KeyData    *key = palloc_object(KeyData);

			*key = record.key;
			CloseTransientFile(fd);
			return key;
		}
	}
	CloseTransientFile(fd);
	return NULL;
}

static void
set_key_by_name(GenericKeyring *keyring, const char *key_name, KeyData *key)
{
	KeyRecord	record;
	off_t		bytes_written = 0;
	off_t		curr_pos = 0;
	int			fd;
	FileKeyring *file_keyring = (FileKeyring *) keyring;
	KeyData    *existing_key;
	KeyringReturnCode return_code = KEYRING_CODE_SUCCESS;

	Assert(key_name != NULL);
	Assert(key != NULL);
	/* See if the key with same name already exists */
	existing_key = get_key_by_name(keyring, key_name, &return_code);
	if (existing_key)
	{
		ereport(ERROR,
				errmsg("Key with name %s already exists in keyring", key_name));
	}

	strlcpy(record.name, key_name, sizeof(record.name));
	record.key = *key;

	fd = OpenTransientFile(file_keyring->file_name, O_CREAT | O_RDWR | PG_BINARY);
	if (fd < 0)
	{
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("Failed to open keyring file %s: %m", file_keyring->file_name));
	}
	/* Write key to the end of file */
	curr_pos = lseek(fd, 0, SEEK_END);
	bytes_written = pg_pwrite(fd, &record, sizeof(record), curr_pos);
	if (bytes_written != sizeof(record))
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
