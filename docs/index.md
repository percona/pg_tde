# `pg_tde` documentation

`pg_tde` is the extension that brings in [Transparent Data Encryption (TDE)](tde.md) to PostgreSQL and enables users to keep sensitive data safe and secure. 

**NOTE**: This is the MVP version of the extension.

`pg_tde` encrypts the following:

* user data in tables, including TOAST tables, that are created using the extension. Metadata of those tables is not encrypted. 
* Write-Ahead Log (WAL) files and temporary tables created during the database operation. Note that only WAL records for tables created using the extension and temporary tables associated with those data tables are encrypted.

The encryption of indexes is planned for the next releases of `pg_tde`.

## Supported PostgreSQL versions

`pg_tde` is currently supported for Percona Distribution for PostgreSQL 16 and PostgreSQL 16. 

## Installation

Install `pg_tde` using one of available installation methods:

* [build from source](#build-from-source)
* [install from a package manually](#install-from-package). Currently only DEB packages are available.
* [run in Docker]

### Build from source

1. To build `pg_tde` from source code, you require the following on Ubuntu/Debian:

    ```sh
    sudo apt install make gcc libjson-c-dev postgresql-server-dev-16
    ```

2. [Install Percona Distribution for PostgreSQL 16] or [upstream PostgreSQL 16] 
3. If PostgreSQL is installed in a non standard directory, set the `PG_CONFIG` environment variable to point to the `pg_config` executable

4. Clone the repository:  

    ```
    git clone git://github.com/Percona-Lab/postgres-tde-ext
    ```

5. Compile and install the extension

    ```
    cd postgres-tde-ext
    make USE_PGXS=1
    sudo make USE_PGXS=1 install
    ```

### Install from package

Currently only DEB packages are available. If you are running RPM-based operating system, consider [building the extension from source](#build-from-source) or [running it in Docker](#run-in-docker)

1. Download the latest [release package](https://github.com/Percona-Lab/postgres-tde-ext/releases)

    ``` sh
    wget https://github.com/Percona-Lab/postgres-tde-ext/releases/download/latest/pgtde-pgdg16.deb
    ```

2. Install the package

    ``` sh
    sudo dpkg -i pgtde-pgdg16.deb
    ```

### Run in Docker

You can find Docker images built from the current main branch on [Docker Hub](https://hub.docker.com/r/perconalab/postgres-tde-ext). Images are built on top of [postgres:16](https://hub.docker.com/_/postgres) official image. 

To run `pg_tde` in Docker, use the following command:

```
docker run --name pg-tde -e POSTGRES_PASSWORD=mysecretpassword -d perconalab/postgres-tde-ext
```

It builds and adds `pg_tde` extension to PostgreSQL 16. Relevant `postgresql.conf` and `tde_conf.json` are created in `/etc/postgresql/` inside the container. This directory is exposed as a volume.

See [Docker Docs](https://hub.docker.com/_/postgres) on usage.

You can also build a Docker image manually with:

```
docker build . -f ./docker/Dockerfile -t your-image-name
```

## Setup

1. Load the `pg_tde` at the start time. The extension requires additional shared memory; therefore,  add the `pg_tde` value for the `shared_preload_libraries` parameter and restart the `postgresql` instance.

2. Start or restart the `postgresql` instance to apply the changes.

    * On Debian and Ubuntu:    

       ```sh
       sudo systemctl restart postgresql.service
       ```
    
    * On RHEL and derivatives

       ```sh
       sudo systemctl restart postgresql-16
       ```

3. Create the extension using the [CREATE EXTENSION](https://www.postgresql.org/docs/current/sql-createextension.html) command. Using this command requires the privileges of a superuser or a database owner. Connect to `psql` as a superuser for a database and run the following command:

    ```sql
    CREATE EXTENSION pg_tde;
    ```

4. Set the location of the keyring configuration file in postgresql.conf: `pg_tde.keyringConfigFile = '/where/to/put/the/keyring.json'`
5. Create the [keyring configuration file](#keyring-configuration)
6. Start or restart the `postgresql` instance to apply the changes.

    * On Debian and Ubuntu:    

       ```sh
       sudo systemctl restart postgresql.service
       ```
    
    * On RHEL and derivatives

       ```sh
       sudo systemctl restart postgresql-16
       ```

### Keyring configuration

```json
{
        'provider': 'file',
        'datafile': '/tmp/pgkeyring',
}
```

Currently the keyring configuration only supports the file provider, with a single datafile parameter.

This datafile is created and managed by PostgreSQL, the only requirement is that `postgres` should be able to write to the specified path.

This setup is intended for developmenet, and stores the keys unencrypted in the specified data file.

## Useful links:

* [What is TDE](tde.md)

