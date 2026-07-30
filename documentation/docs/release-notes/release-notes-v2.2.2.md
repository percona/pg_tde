# pg_tde 2.2.2 ({{date.2_2_2}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

`pg_tde` 2.2.2 focuses on fixing an issue with performance of WAL encryption and adding support for KMIP with HashiCorp Vault Enterprise. Vault Enterprise was already supported via the Vault V2 protocol, but now KMIP can be used too.

!!! warning
    `pg_tde` 2.2.2 is not compatible with Percona Distribution for PostgreSQL older than 17.10.2 or 18.4.2.

## Known issues

* The default `mlock` limit on Rocky Linux 8 for ARM64-based architectures equals the memory page size and is 64 Kb. This results in the child process with `pg_tde` failing to allocate another memory page because the max memory limit is reached by the parent process.

    To prevent this, you can change the `mlock` limit to be at least twice the memory page size:

    * temporarily for the current session using the `ulimit -l <value>` command.
    * set a new hard limit in the `/etc/security/limits.conf` file. To do so, you require the superuser privileges.

    Adjust the limits with caution since it affects other processes running in your system.

## Changelog

Changes introduced in `pg_tde` 2.2.2:

### New Features

- [PG-2125](https://perconadev.atlassian.net/browse/PG-2125) - Support using HashiCorp Vault Enterprise with KMIP
- [PG-2473](https://perconadev.atlassian.net/browse/PG-2473) - Basic support for building on Windows with Microsoft Visual C++

### Improvements

- [PG-2494](https://perconadev.atlassian.net/browse/PG-2494) - Improved performance of WAL encryption

### Bug Fixes

- [PG-2492](https://perconadev.atlassian.net/browse/PG-2492) - Fixed crash when empty certificate parameters are passed to `pg_tde_add_global_key_provider_kmip()` or `pg_tde_add_database_key_provider_kmip()`
- [PG-2608](https://perconadev.atlassian.net/browse/PG-2608) - Fixed a race condition in the Vault key provider that could occur when multiple processes accessed the same cURL handle after a fork.
- [PG-2609](https://perconadev.atlassian.net/browse/PG-2609) - Fixed WAL archiving (`pg_tde_archive_decrypt` and `pg_tde_restore_encrypt`) when pg_wal dir is a symlink.
