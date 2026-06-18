# Upgrade pg_tde

The version of `pg_tde` available to you depends on your version of Percona Distribution for PostgreSQL.

To use a newer `pg_tde` release, first ensure that your Percona Distribution for PostgreSQL version includes it.

This document describes upgrading the `pg_tde` extension within the same PostgreSQL major version. For PostgreSQL major version upgrades on clusters that use `pg_tde`, use [pg_tde_upgrade](../command-line-tools/pg-tde-upgrade.md).

## Before you start

!!! note
    `pg_tde` 2.2.0 is not compatible with Percona Distribution for PostgreSQL older than 17.10 or 18.4. Upgrade your distribution first before upgrading `pg_tde`.

!!! warning
    Using `pg_upgrade` on an encrypted cluster is not supported and will result in data corruption. The server may start successfully but queries against encrypted tables will fail.

## Procedure

1. Take a full [backup before upgrading](./backup-wal-enabled.md).

2. Upgrade the `pg_tde` package via your package manager.

3. Restart the `postgresql` service.

4. Connect to each database where `pg_tde` is installed and run:

    ```sql
    ALTER EXTENSION pg_tde UPDATE;
    ```

    !!! note
        The catalog version of `pg_tde` may not change between patch releases. You can run `ALTER EXTENSION pg_tde UPDATE` safely regardless.

5. Verify the upgrade:

```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_tde';
SELECT pg_tde_version();
```
