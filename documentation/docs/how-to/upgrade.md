# Upgrade pg_tde

The version of `pg_tde` available to you depends on your version of Percona Distribution for PostgreSQL. To get a newer version of `pg_tde`, upgrade your Percona Distribution for PostgreSQL to the version that includes it. For more information, see [Upgrading Percona Distribution for PostgreSQL from 17 to 18 :octicons-link-external-16:](https://docs.percona.com/postgresql/18/major-upgrade.html).

## Before you start

!!! note
    `pg_tde` 2.2.0 is not compatible with Percona Distribution for PostgreSQL older than 17.10 or 18.4. Upgrade your distribution first before upgrading `pg_tde`.

!!! warning
    If your cluster uses `pg_tde`, you **must** use `pg_tde_upgrade` instead of `pg_upgrade` when performing a major PostgreSQL version upgrade. The server may start successfully but queries against encrypted tables will fail.

## Procedure

1. Upgrade `pg_tde` package via your package manager.

2. Restart the `postgresql` service.

3. Connect to each database where `pg_tde` is installed and run:

    ```sql
        ALTER EXTENSION pg_tde UPDATE;
    ```

    !!! note
        This needs to be run in each database where `pg_tde` is installed.
