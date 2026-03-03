# pg_tde_waldump

[`pg_tde_waldump` :octicons-link-external-16:](https://www.postgresql.org/docs/current/pgwaldump.html) displays a human-readable rendering of the Write-Ahead Log (WAL) for a PostgreSQL database cluster.

To read encrypted WAL records, `pg_tde_waldump` provides the following additional option:

* `-k, --keyring-path=PATH` is the path to the directory containing the WAL keyring configuration files. This is typically the `pg_tde/` directory inside the PostgreSQL data directory. The following files are included:
    * `wal_keys`
    * `1664_providers`

!!! note
    `pg_tde_waldump` cannot read encrypted WAL unless `--keyring-path` is specified.
