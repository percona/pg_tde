# pg_tde_waldump

[`pg_tde_waldump` :octicons-link-external-16:](https://www.postgresql.org/docs/current/pgwaldump.html) is a tool to display a human-readable rendering of the Write-Ahead Log (WAL) of a PostgreSQL database cluster.

To read encrypted WAL records, `pg_tde_waldump` supports the following additional arguments:

* `keyring_path` is the directory where the keyring configuration files for WAL are stored. The following files are included:
    * `wal_keys`
    * `1664_providers`

!!! note
    `pg_tde_waldump` cannot read encrypted WAL unless the `keyring_path` is set.
