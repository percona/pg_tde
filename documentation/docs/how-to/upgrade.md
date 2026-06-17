# Upgrade pg_tde

The version of `pg_tde` available to you depends on your version of Percona Distribution for PostgreSQL. To get a newer version of `pg_tde`, upgrade your Percona Distribution for PostgreSQL to the version that includes it. For more information, see [Upgrading Percona Distribution for PostgreSQL from 17 to 18 :octicons-link-external-16:](https://docs.percona.com/postgresql/18/major-upgrade.html).

This topic covers upgrading the `pg_tde` extension to a newer version within the **same** PostgreSQL major version.

## Before you start

!!! note
    `pg_tde` 2.2.0 is not compatible with Percona Distribution for PostgreSQL older than 17.10 or 18.4. Upgrade your distribution first before upgrading `pg_tde`.

!!! warning
    When doing a major version upgrade from Percona Distribution for PostgreSQL 17, if your cluster uses `pg_tde`, you **must** use [`pg_tde_upgrade` :octicons-link-external-16:](../command-line-tools/pg-tde-upgrade.md) instead of `pg_upgrade`. Using `pg_upgrade` on an encrypted cluster is not supported and will result in data corruption. The server may start successfully but queries against encrypted tables will fail.

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
