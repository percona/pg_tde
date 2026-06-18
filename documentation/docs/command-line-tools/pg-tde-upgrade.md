# pg_tde_upgrade

`pg_tde_upgrade` wraps [`pg_upgrade` :octicons-link-external-16:](https://www.postgresql.org/docs/current/pgupgrade.html) to simplify upgrading clusters with encrypted relations or WAL. It can also be run safely on clusters without `pg_tde` enabled.

## Implementation

`pg_tde_upgrade` copies the `pg_tde` subdirectory from the old data directory to the new data directory and then runs `pg_upgrade` as normal except for using `pg_tde_resetwal` instead of `pg_resetwal`.

!!! note
    Ensure that `pg_tde` is included in `shared_preload_libraries` and that you have the right setting for [`pg_tde.wal_encrypt`](../variables.md#pg_tdewal_encrypt) in the new cluster.

For more information on how to perform the upgrade for major versions, see [Upgrading Percona Distribution for PostgreSQL from 17 to 18 :octicons-link-external-16:](https://docs.percona.com/postgresql/18/major-upgrade.html#upgrading-percona-distribution-for-postgresql-from-17-to-18).

For more information on how to perform the upgrade for minor versions or within the same version of your Percona Distribution for PostgreSQL, see [Upgrade pg_tde](../how-to/upgrade.md).
