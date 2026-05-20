# pg_tde 2.2.0 ({{date.2_2_0}})

The `pg_tde` extension, provided by Percona, adds [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and helps protect sensitive data at rest.

[Get Started](../install.md){.md-button}

## Release Highlights

`pg_tde` now supports 256-bit AES encryption and introduces [`pg_tde_upgrade`](../command-line-tools/pg-tde-upgrade.md), a utility that simplifies the upgrades of encrypted clusters. For more details, see the [Changelog](#changelog).

!!! warning
    `pg_tde` 2.2.0 requires Percona Distribution for PostgreSQL 17.10 or 18.4. It is not compatible with earlier versions of the distribution.

### Documentation updates

* The [Limitations of pg_tde](../index/tde-limitations.md) topic is updated to include a new section on known incompatibilities with Citus and TimescaleDB, and a clarification of the `ALTER DATABASE ... SET TABLESPACE` behavior, the command can be used but with restrictions when `pg_tde` is active.
* The [Backup with WAL encryption enabled](../how-to/backup-wal-enabled.md) topic is updated with a clearer description of the key rotation limitation during backups.

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

Changes introduced in `pg_tde` 2.2.0:

### New Features

- [PG-1968](https://perconadev.atlassian.net/browse/PG-1968) - AES-256 encryption support, `pg_tde` now supports 256-bit AES encryption, providing stronger cryptographic protection for encrypted tablespaces.
- [PG-2017](https://perconadev.atlassian.net/browse/PG-2017) - AES-256 compatibility for `pg_tde_resetwal`, the `pg_tde_resetwal` utility has been updated to work correctly with AES-256 encrypted data.
- [PG-2018](https://perconadev.atlassian.net/browse/PG-2018) - AES-256 compatibility for `pg_tde_basebackup`, the `pg_tde_basebackup` utility now fully supports AES-256 encryption, ensuring consistent backup and restore behavior for databases using the new cipher.
- [PG-2240](https://perconadev.atlassian.net/browse/PG-2240) - Introducing `pg_tde_upgrade`, a utility that automates the steps required to upgrade a `pg_tde`-enabled cluster, making the upgrade process more convenient.

### Improvements

- [PG-2278](https://perconadev.atlassian.net/browse/PG-2278) - Storage manager (SMGR) encryption has been optimized to reuse OpenSSL cipher contexts, reducing overhead and improving throughput for encrypted I/O operations.

### Bug Fixes

- [PG-2240](https://perconadev.atlassian.net/browse/PG-2240) - Fixed an issue where `pg_upgrade` would fail when run against databases containing encrypted data.
- [PG-1895](https://perconadev.atlassian.net/browse/PG-1895) - Resolved a bug where performing WAL key rotation or SMGR key rotation during a `pg_basebackup` operation could prevent the secondary server from starting successfully.
- [PG-2125](https://perconadev.atlassian.net/browse/PG-2125) - Fixed key creation failures that occurred when `pg_tde` was configured to use HashiCorp Vault via the KMIP protocol.
