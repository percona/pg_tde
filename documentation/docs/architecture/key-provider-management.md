# Key and key provider management

`pg_tde` uses a hierarchy of principal and internal keys to encrypt database files. This chapter covers how to manage these keys, including rotation, regeneration, storage, and key provider configuration, so you can keep your encrypted data secure and accessible.

## Principal key rotation

You can rotate principal keys to comply with common policies and to handle situations with potentially exposed principal keys.

Rotation means that `pg_tde` generates a new version of the principal key, and re-encrypts the associated internal keys with the new key. The old principal key is kept as is at the same location, because it may still be needed to decrypt backups or other databases.

## Internal key regeneration

Internal keys for tables, indexes and other data files are generated once a file is created. There's no way to re-encrypt a file.

There are workarounds for this, because operations that move the table data to a new file, such as `VACUUM FULL` or an `ALTER TABLE` that rewrites the file will create a new key for the new file, essentially rotating the internal key. This however means taking an exclusive lock on the table for the duration of the operation, which might not be desirable for huge tables.

WAL internal keys are fixed once created. Every time the server (re)starts, a new WAL key is generated. If WAL encryption is enabled (using `pg_tde.wal_encrypt`), all WAL writes following the creation of the new key are encrypted with it until **another** key is generated at the next restart. This ensures that each WAL segment uses a consistent encryption key, without requiring you to manage key rotation manually.

## Internal key storage

Internal keys and `pg_tde` metadata in general are kept in a single `$PGDATA/pg_tde` directory. This directory stores separate files for each database, such as:

* Encrypted internal keys and internal key mapping to tables
* Information about the key providers

Also, the `$PGDATA/pg_tde` directory has a special global section marked with the OID `1664`, which includes the global key providers and global internal keys.

The global section is used for WAL encryption. Specific databases can use the global section too, for scenarios where users configure individual principal keys for databases but use the same global key provider. For this purpose, you must enable the global provider inheritance.

The global default principal key uses the special OID `1663`.

## Key providers (principal key storage)

In `pg_tde`, a Key Management System (KMS) is treated as an external key provider. Key providers store and serve the principal keys that `pg_tde` uses for encryption and decryption.

When you configure a key provider, `pg_tde`:

* Uploads new principal keys when they are created
* Retrieves principal keys from the provider when needed for decryption (for example, at startup or restart)
* Caches retrieved keys to reduce repeated lookups

!!! note
    Each key provider requires a detailed configuration, including the service address and authentication information.

For a complete list of supported providers and their configuration steps, see the [Key management overview](../global-key-provider-configuration/overview.md).

## Key provider management

Key provider configuration or location may change. For example, a service is moved to a new address or the principal key must be moved to a different key provider type. `pg_tde` supports both these scenarios enabling you to manage principal keys using simple [SQL functions](../functions.md#key-provider-management).

In certain cases you can't use SQL functions to manage key providers. For example, if the key provider changed while the server wasn't running and is therefore unaware of these changes. The startup can fail if it needs to access the encryption keys.

For such situations, `pg_tde` also provides [command line tools](../command-line-tools/cli-tools.md) to recover the database.

## Sensitive key provider information

!!! important
    Authentication details for key providers are sensitive and must be protected.
    Do not store these credentials in the `$PGDATA` directory alongside the database. Instead, ensure they are stored in a secure location with strict file system permissions to prevent unauthorized access.
