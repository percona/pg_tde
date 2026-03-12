# pg_tde_upgrade

`pg_tde_upgrade` wraps [`pg_upgrade` :octicons-link-external-16:](https://www.postgresql.org/docs/current/pgupgrade.html) to simplify the procedure for upgrading clusters with encrypted relations or WAL. It can also be safely run on clusters without `pg_tde` enabled.

## Implementation

`pg_tde_upgrade` copies the `pg_tde` subdirectory from the old data directory to the new data directory and then runs `pg_upgrade` as normal except for using `pg_tde_resetwal` instead of `pg_resetwal`.

!!! note
    Make sure that `pg_tde` is included in `shared_preload_libraries` and that you have the right setting for `pg_tde.wal_encrypt` for the new cluster.
