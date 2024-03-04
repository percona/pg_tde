# Functions

The `pg_tde` extension provides the following functions:

## pg_tde_add_key_provider_file

Creates a new key provider for the database using a local file.

This function is intended for development, and stores the keys unencrypted in the specified data file.

```sql
SELECT pg_tde_add_key_provider_file('provider-name','/path/to/the/keyring/data.file');
```

## pg_tde_add_key_provider_vault_v2

Creates a new key provider for the database using a remote HashiCorp Vault server.

The specified access parameters require permission to read and write keys at the location.

```sql
SELECT pg_tde_add_key_provider_vault_v2('provider-name',:'secret_token','url','mount','ca_path');
```

where:

* `url` is the URL of the Vault server
* `mount` is the mount point where the keyring should store the keys
* `secret_token` is an access token with read and write access to the above mount point
* [optional] `ca_path` is the path of the CA file used for SSL verification

## pg_tde_set_master_key

Sets the master key for the database using the specified provider.

Th master key name is also used for constructing the name in the provider, for example on the remote
Vault server.

This function can only be used for creating a master key, later changes require using the 

```sql
SELECT pg_tde_set_master_key('name-of-the-master-key', 'provider-name');
```

## pg_tde_rotate_key

Creates a new version of the specified master key, and updates the database so it uses it.

Not yet implemented.

```sql
SELECT pg_tde_rotate_key('name-of-the-master-key');
```

## pg_tde_is_encrypted

Tells if a table is using the pg_tde access method or not.

```sql
SELECT pg_tde_is_encrypted('table_name');
```