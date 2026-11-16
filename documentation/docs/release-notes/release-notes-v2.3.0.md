# pg_tde 2.3.0 ({{date.2_3_0}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

`pg_tde` 2.3.0 adds support for PostgreSQL 19 and makes `pg_tde_waldump` aware of the `pg_tde` custom resource manager. For more details, see the [Changelog](#changelog).

## Known issues

* The default `mlock` limit on Rocky Linux 8 for ARM64-based architectures equals the memory page size and is 64 Kb. This results in the child process with `pg_tde` failing to allocate another memory page because the max memory limit is reached by the parent process.

    To prevent this, you can change the `mlock` limit to be at least twice the memory page size:

    * temporarily for the current session using the `ulimit -l <value>` command.
    * set a new hard limit in the `/etc/security/limits.conf` file. To do so, you require the superuser privileges.

    Adjust the limits with caution since it affects other processes running in your system.

## Changelog

Changes introduced in `pg_tde` 2.3.0:

### New Features

- [PG-2536](https://perconadev.atlassian.net/browse/PG-2536), [PG-2813](https://perconadev.atlassian.net/browse/PG-2813) - Support for PostgreSQL 19

### Improvements

- [PG-2754](https://perconadev.atlassian.net/browse/PG-2754) - `pg_tde_waldump` now recognises the `pg_tde` custom resource manager, prints proper data for its records and accepts it in the `--rmgr` filter
