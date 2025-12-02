# pg_tde 2.1 ({{date.2_1}})

The `pg_tde` by Percona extension brings [Transparent Data Encryption (TDE)](../index/about-tde.md) to PostgreSQL and enables you to keep sensitive data safe and secure.

[Get Started](../install.md){.md-button}

## Release Highlights

### Added support for PostgreSQL 18.1

`pg_tde` is fully supported with the Postgres 18.1 version.

### Packaging changes for PostgreSQL 18

Starting with PostgreSQL 18, `pg_tde` is distributed as a **standalone package** for RPM and DEB installations.

It is no longer bundled with the main PostgreSQL server package.

If your PostgreSQL 18 deployment uses `pg_tde`, make sure to install the matching `pg_tde` package separately.

Percona’s PostgreSQL **Docker images continue to include `pg_tde` by default**, so no additional action is required for container-based deployments.

For more information on the availability by PostgreSQL version, please see [Install pg_tde](../install.md).

### Added support for AIO

Added support for **asynchronous I/O (AIO)** which is now the default I/O mechanism.

### Repository split for multi-version PostgreSQL support

Reorganized the project into a multi-repository structure to support several PostgreSQL versions more efficiently.

### Tooling changes

The standard PostgreSQL command-line utilities can no longer operate on clusters encrypted with `pg_tde`. To manage encrypted data safely, use the `pg_tde_` equivalents provided by Percona:

* pg_basebackup to pg_tde_basebackup
* pg_checksums to pg_tde_checksums
* pg_resetwal to pg_tde_resetwal
* pg_rewind to pg_tde_rewind
* pg_waldump to pg_tde_waldump

!!! warning

    The non-pg_tde_* versions will not work on encrypted clusters and may fail with errors if used. Always use the `pg_tde_` variants when working with TDE-enabled data.

### Added Akeyless support

`pg_tde` is now compatible with the Akeyless CipherTrust Manager via the KMIP protocol. For more information, see the [Key management overview topic](../global-key-provider-configuration/overview.md).

### Added support for Vault and OpenBao namespaces

Implemented support for the "namespace" feature in Vault Enterprise and OpenBao, available both on the CLI and on the HTTP interface using the `X-Vault-Namespace` header.

### Documentation updates

- Added the [Akeyless topic](../global-key-provider-configuration/kmip-akeyless.md)
- Added the [Impact of pg_tde on database operations](../index/what-tde-impacts.md) topic which summarizes how `pg_tde` interacts with core PostgreSQL operations
- Updated the [FAQ](../faq.md) with an answer to logical replication keeping data encrypted on subscribers
- Updated [Install pg_tde](../install.md) with a table for the `pg_tde` availability by PostgreSQL version
- Added support for HashiCorp Vault namespaces in [Add or modify Vault providers](../functions.md#add-or-modify-vault-providers). The `namespace` parameter is now documented and fully supported.

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
