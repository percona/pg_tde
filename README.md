# pg_tde: Transparent Database Encryption for PostgreSQL

`Experimental` PostgreSQL extension that provides data encryption at rest on table level. [We need your feedback!](https://github.com/percona/pg_tde/discussions/151)

## Overview
Transparent Data Encryption offers encryption at the file level and solves the problem of protecting data at rest. The encryption is transparent for users allowing them to access and manipulate the data and not to worry about the encryption process. As a key provider extension supports file and [Hashicorp Vault](https://www.vaultproject.io/).

### This extension provides two `access methods` with different options:

#### `tde_heap_basic` access method
- Works with community PostgreSQL 16 and 17
- Encrypts tuples and WAL
- **Doesn't** encrypt indexes
- CPU expensive as it decrypts pages each time they read from bufferpool 

#### `tde_heap` access method
- Works only with [Percona Server for PosgreSQL 17](https://docs.percona.com/postgresql/17/postgresql-server.html)
- Uses extended Storage Manager and WAL APIs
- Encrypts tupes, WAL and indexes
- Faster and cheaper than `tde_heap_basic`

## Documentation

Full and comprehensive documentation about `pg_tde` available at https://percona.github.io/pg_tde/.

## Installation

### Pecona Server for PostgreSQL (`pg_tde` included) with package manager

   1. Install [percona-release](https://docs.percona.com/percona-software-repositories/installing.html) tool to configure repositories
   2. Enable Percona Distribuition for PostgreSQL repository  
        ```
        sudo percona-release enable-only ppg-17
        ```
   3. Install Percona Server for PosrgreSQL
    - For Debian and Ubuntu
        ```
        sudo apt update
        sudo apt install percona-ppg-server-17
        ```
   - For RHEL 8 compatible OS
        ```
        sudo yum install percona-ppg-server17
        ```

### Extension only with package manager

  1. Install [percona-release](https://docs.percona.com/percona-software-repositories/installing.html) tool to configure repositories
  2. Enable Percona Distribuition for PostgreSQL repository (replace XX with 16 or 17) 
        ```
        sudo percona-release enable-only ppg-XX
        ```

  3. Install `pg_tde` extension (replace XX with 16 or 17)
   - For Debian or Ubuntu
        ```
        sudo apt update
        sudo apt install percona-postgresql-XX-pg-tde
        ```
   - For RHEL 8 compatible OS
        ```
        sudo yum install percona-pg_tde_XX
        ```


### Extension only from sources
  1. Install required dependencies:
   - On Debian and Ubuntu:
        ```sh
        sudo apt install make gcc autoconf libcurl4-openssl-dev postgresql-server-dev-16
        ```
     
   - On RHEL 8 compatible OS:
     ```sh
     sudo yum install epel-release
     yum --enablerepo=powertools install git make gcc autoconf libcurl-devel postgresql16-devel perl-IPC-Run redhat-rpm-config openssl-devel
     ```
       
   - On MacOS:
     ```sh
     brew install make autoconf curl gettext postresql@16
     ```

  2. Install or build postgresql 16 [(see reference commit below)](#base-commit)
  3. If postgres is installed in a non standard directory, set the `PG_CONFIG` environment variable to point to the `pg_config` executable

  4. Clone the repository, build and install it with the following commands:  

     ```
     git clone https://github.com/percona/pg_tde
     ```
  
   5. Compile and install the extension

      ```
      cd pg_tde
      ./configure
      make USE_PGXS=1
      sudo make USE_PGXS=1 install
      ```

_See [Make Builds for Developers](https://github.com/percona/pg_tde/wiki/Make-builds-for-developers) for more info on the build infrastructure._

## Setting up

  1. Add extension to `shared_preload_libraries`:
      1. Via configuration file `postgresql.conf `
            ```
            shared_preload_libraries=pg_tde 
            ```
      2. Via SQL using [ALTER SYSTEM](https://www.postgresql.org/docs/current/sql-altersystem.html) command
            ```
            ALTER SYSTEM SET shared_preload_libraries = 'pg_tde';
            ```
   2. Start or restart the `postgresql` instance to apply the changes.
      * On Debian and Ubuntu:

        ```sh
        sudo systemctl restart postgresql.service
        ```

      * On RHEL 8 compatible OS (replace XX with your version):
        ```sh
        sudo systemctl restart postgresql-XX.service
        ``` 
   3. [CREATE EXTENSION](https://www.postgresql.org/docs/current/sql-createextension.html) with SQL (requires superuser or a database owner privileges):

        ```sql
        CREATE EXTENSION pg_tde;
        ```
   4. Create a key provider. Currently `pg_tde` supports `File` and `Vault-V2` key providers. You can add the required key provider using one of the functions.
   
        ```sql
        -- For Vault-V2 key provider
        pg_tde_add_key_provider_vault_v2(
                                provider_name VARCHAR(128),
                                vault_token TEXT,
                                vault_url TEXT,
                                vault_mount_path TEXT,
                                vault_ca_path TEXT);

        -- For File key provider
        FUNCTION pg_tde_add_key_provider_file(
                                provider_name VARCHAR(128), 
                                file_path TEXT);

        ```
        **Example**: Add a `File` key provider and name it `file`.
        ```sql
        SELECT pg_tde_add_key_provider_file('file','/tmp/pgkeyring');
        ```
        **Note: The `File` provided is intended for development and stores the keys unencrypted in the specified data file.**

   5. Set the principal key for the database using the `pg_tde_set_principal_key` function.
        ```sql
        FUNCTION pg_tde_set_principal_key (
                        principal_key_name VARCHAR(255), 
                        provider_name VARCHAR(255));
        ```
        **Example**: Set the principal key named `my-principal-key` using the `file` as a key provider.
        ```sql
        SELECT pg_tde_set_principal_key('my-principal-key','file');
        ```
   
   6. Specify `tde_heap_basic` or `tde_heap` access method during table creation
        ```sql
        CREATE TABLE albums (
            album_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            artist_id INTEGER,
            title TEXT NOT NULL,
            released DATE NOT NULL
        ) USING tde_heap_basic;
        ```
   7. You can encrypt existing table. It requires rewriting the table, so for large tables, it might take a considerable amount of time. 
        ```
        ALTER TABLE table_name SET access method  tde_heap_basic;
        ```


## Latest test release

To download the latest build of the main branch, use the `HEAD` release from [releases](https://github.com/percona/pg_tde/releases).

Builds are available in a tar.gz format, containing only the required files, and as a deb package.
The deb package is built against the pgdg16 release, but this dependency is not yet enforced in the package.


## Run in Docker

You can find docker images built from the current main branch on [Docker Hub](https://hub.docker.com/r/perconalab/pg_tde). Images build on top of [postgres:16](https://hub.docker.com/_/postgres) official image. To run it:
```
docker run --name pg-tde -e POSTGRES_PASSWORD=mysecretpassword -d perconalab/pg_tde
```
It builds and adds `pg_tde` extension to Postgres 16. Relevant `postgresql.conf` and `tde_conf.json` are created in `/etc/postgresql/` inside the container. This dir is exposed as volume.

See https://hub.docker.com/_/postgres on usage.

You can also build a docker image manually with:
```
docker build . -f ./docker/Dockerfile -t your-image-name
```

## Helper functions

The extension provides the following helper functions:

### pg_tde_is_encrypted(tablename)

Returns `t` if the table is encrypted (uses the tde_heap_basic access method), or `f` otherwise.

## Base commit

This is based on the heap code as of the following commit:

```
commit a81e5516fa4bc53e332cb35eefe231147c0e1749 (HEAD -> REL_16_STABLE, origin/REL_16_STABLE)
Author: Amit Kapila <akapila@postgresql.org>
Date:   Wed Sep 13 09:48:31 2023 +0530

    Fix the ALTER SUBSCRIPTION to reflect the change in run_as_owner option.
```

