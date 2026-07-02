# pg_tde 2.2.1 ({{date.2_2_1}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

`pg_tde` now supports 256-bit AES encryption and introduces [`pg_tde_upgrade`](../command-line-tools/pg-tde-upgrade.md), a utility that simplifies the upgrades of encrypted clusters. For more details, see the [Changelog](#changelog).

!!! warning
    `pg_tde` 2.2.1 is not compatible with Percona Distribution for PostgreSQL older than 17.10 or 18.4.

## Known issues

* `pg_rewind` and `pg_tde_rewind`

    Using `pg_rewind` or `pg_tde_rewind` between diverged nodes in clusters that use `pg_tde` may lead to corrupted tables or indexes due to internal encryption key differences between clusters.

    Queries may fail with:

    ```bash
    ERROR: invalid page in block 0 of relation "base/..."
    ```

    This behavior is a known issue.

    For more information, see [pg_tde limitations](../index/tde-limitations.md).

* The default `mlock` limit on Rocky Linux 8 for ARM64-based architectures equals the memory page size and is 64 Kb. This results in the child process with `pg_tde` failing to allocate another memory page because the max memory limit is reached by the parent process.

    To prevent this, you can change the `mlock` limit to be at least twice the memory page size:

    * temporarily for the current session using the `ulimit -l <value>` command.
    * set a new hard limit in the `/etc/security/limits.conf` file. To do so, you require the superuser privileges.

    Adjust the limits with caution since it affects other processes running in your system.

## Changelog

Changes introduced in `pg_tde` 2.2.1:

### New Features

### Improvements

### Bug Fixes

### Documentation updates
