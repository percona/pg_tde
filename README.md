# pg_tde

This is an experimental encrypted access method for Postgres 16.

## Installation steps

1. Build and install the plugin either with make or meson (see build steps)
2. Add pg_tde to the preload libraries: `ALTER SYSTEM SET shared_preload_libraries = 'pg_tde';`
3. Restart the postgres server
4. Create the extension: `CREATE EXTENSION pg_tde;`
5. Set the location of the keyring configuration file in postgresql.conf: `pg_tde.keyringConfigFile = '/where/to/put/the/keyring.json'`
6. Create the keyring configuration file (see example keyring configuration)
7. Restart the postgres server

## Keyring configuration

```json
{
        'provider': 'file',
        'datafile': '/tmp/pgkeyring',
}
```

Currently the keyring configuration only supports the file provider, with a single datafile parameter.
This datafile is created and managed by Postgres, the only requirement is that postgres should be able to write to the specified path.

This setup is intended for developmenet, and stores the keys unencrypted in the specified data file.

## Build steps

1. Install libjson-c-dev, for example on Ubuntu/Debian: `apt install libjon-c-dev`
2. Install or build postgresql 16 (see reference commit below)
3. If postgres is installed in a non standard directory, set the `PG_CONFIG` environment variable to point to the `pg_config` executable
4. In the pg_tde directory: `make USE_PGXS=1` and `make USE_PGXS=1 install`

## Base commit

This is based on the heap code as of the following commit:

```
commit 93dcdfa88f5f9befb781558920e02d3ee86dc629
Author: Tom Lane <tgl@sss.pgh.pa.us>
Date:   Mon Jul 10 12:14:34 2023 -0400
```
