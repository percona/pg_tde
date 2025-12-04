# Overview of pg_tde CLI tools

The `pg_tde` extension provides a set of command-line utilities designed specifically for operating on  encrypted data and clusters. These utilities exist in parallel with the standard PostgreSQL utilities but you **must** use them when working with data encrypted by `pg_tde`.

!!! note
    The standard PostgreSQL tools cannot operate on `pg_tde`-encrypted WAL or tables.

## New `pg_tde` specific tools

These tools are introduced exclusively by `pg_tde` to support key rotation and WAL encryption workflows:

* [pg_tde_change_key_provider](./pg-tde-change-key-provider.md): change the encryption key provider for a database
* [pg_tde_archive_decrypt](./pg-tde-archive-decrypt.md): decrypts WAL before archiving
* [pg_tde_restore_encrypt](./pg-tde-restore-encrypt.md): a custom restore command for making sure the restored WAL is encrypted

## Tools for working with `pg_tde`-encrypted data

These tools are modified versions of standard PostgreSQL utilities that include `pg_tde` support. You must use the `pg_tde_*` variants when working with encrypted WAL or tables:

* [pg_tde_checksums](./pg-tde-checksums.md): verify data checksums (non-encrypted files only)
* [pg_tde_waldump](./pg-tde-waldump.md): inspect and decrypt WAL files
* [pg_tde_basebackup](../how-to/backup-wal-enabled.md): create base backups that include encrypted data
* pg_tde_resetwal: reset the WAL for clusters using `pg_tde`
* pg_tde_rewind: rewind clusters that use encrypted WAL
