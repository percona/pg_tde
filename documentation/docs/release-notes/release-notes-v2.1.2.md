# pg_tde 2.1.2 ({{date.2_1_2}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

### Documentation updates

* The [Architecture](../architecture/overview.md) documentation is redesigned for improved clarity and readability. The chapter is now split into smaller, more focused sections.
* The [Technical reference overview](../tech-reference.md) is updated with quick-skim cards for quick topic access.
* A dedicated [Usage reference](../advanced-topics/usage-guide.md) topic is introduced which describes the main `pg_tde` operations available.

## Known issues

* Do not create, change, or rotate global key providers (or their keys) while `pg_tde_basebackup` is running. Doing so may cause standbys or clusters initialized from the backup to fail during WAL replay and may result in corruption of encrypted data (tables, indexes, and other relations).

* Using `pg_tde_basebackup` with `--wal-method=fetch` produces warnings.

    This behavior is expected and will be addressed in a future release.

* The default `mlock` limit on Rocky Linux 8 for ARM64-based architectures equals the memory page size and is 64 Kb. This results in the child process with `pg_tde` failing to allocate another memory page because the max memory limit is reached by the parent process.

    To prevent this, you can change the `mlock` limit to be at least twice bigger than the memory page size:

    * temporarily for the current session using the `ulimit -l <value>` command.
    * set a new hard limit in the `/etc/security/limits.conf` file. To do so, you require the superuser privileges.

    Adjust the limits with caution since it affects other processes running in your system.

## Changelog

### Improvements

* [PG-2088 :octicons-link-external-16:](https://perconadev.atlassian.net/browse/PG-2088), [PG-2179 :octicons-link-external-16:](https://perconadev.atlassian.net/browse/PG-2179) - Improved handling of Vault/OpenBao KV v2 mount point validation in `pg_tde`. The extension no longer fails when configured with tokens that lack access to mount metadata endpoints and now works correctly with tokens that have only the required KV v2 read/write permissions.

### Bugs Fixed

* Updated `pg_tde` CLI tools to include upstream bug fixes and stability improvements from PostgreSQL 18.1.
