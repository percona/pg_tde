# pg_tde 2.1.2 ({{date.2_1_2}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

### Documentation updates

* Reorganized and redesigned the Architecture documentation for improved clarity and readability. The chapter is now split into smaller, focused sections, adds a Technical Reference overview with quick-skim cards, and introduces a dedicated Usage Guide for deploying and operating `pg_tde`.

## Known issues

* Creating, changing, or rotating global key providers (or their keys) while `pg_tde_basebackup` is running may cause standbys or standalone clusters initialized from the backup to fail during WAL replay and may also lead to the corruption of encrypted data (tables, indexes, and other relations).

    Avoid making these actions during backup windows. Run a new full backup after completing a rotation or provider update.

* Using `pg_tde_basebackup` with `--wal-method=fetch` produces warnings.

    This behavior is expected and will be addressed in a future release.

* The default `mlock` limit on Rocky Linux 8 for ARM64-based architectures equals the memory page size and is 64 Kb. This results in the child process with `pg_tde` failing to allocate another memory page because the max memory limit is reached by the parent process.

    To prevent this, you can change the `mlock` limit to be at least twice bigger than the memory page size:

    * temporarily for the current session using the `ulimit -l <value>` command.
    * set a new hard limit in the `/etc/security/limits.conf` file. To do so, you require the superuser privileges.

    Adjust the limits with caution since it affects other processes running in your system.

## Changelog

### Improvements

* [PG-2088 :octicons-link-external-16:](https://perconadev.atlassian.net/browse/PG-2088) - Improved handling of Vault KV v2 mount point checks to avoid permission-related failures when configuring `pg_tde` with HashiCorp Vault or OpenBao.

### Bugs Fixed

* [PG-2179 :octicons-link-external-16:](https://perconadev.atlassian.net/browse/PG-2179) - Fixed a fatal error in ``pg_tde`` when using Vault/OpenBao keyring providers with tokens that lack access to mount metadata endpoints. ``pg_tde`` now works correctly with tokens that have only the required KV v2 read/write permissions.
