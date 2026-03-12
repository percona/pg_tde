# Limitations of pg_tde

## Known incompatibilities in Percona Server for PostgreSQL

Some PostgreSQL extensions may not work with Percona Server for PostgreSQL due to internal changes required by `pg_tde`.

These incompatibilities may occur even if `pg_tde` is not installed or enabled.

### Distributed and extension-based systems

!!! warning "Citus and TimescaleDB are not supported"
    Percona Server for PostgreSQL is not compatible with distributed PostgreSQL extensions such as Citus or time-series extensions such as TimescaleDB.

    This limitation is caused by internal PostgreSQL changes related to `pg_tde` and is not dependent on enabling the extension.

## Limitations when using pg_tde

Limitations of `pg_tde` {{release}}:

* PostgreSQL’s internal system tables, which include statistics and metadata, are not encrypted.
* Temporary files created when queries exceed `work_mem` are not encrypted. These files may persist during long-running queries or after a server crash which can expose sensitive data in plaintext on disk.

## Recovery without `pg_tde` in `shared_preload_libraries`

!!! danger "Risk of corruption when recovering encrypted clusters without pg_tde loaded"
    When recovering a PostgreSQL cluster that contains encrypted tables, the `pg_tde` extension must be loaded through the `shared_preload_libraries` configuration parameter.

## `pg_rewind` and `pg_tde_rewind`

!!! danger "Risk of corruption when using `pg_rewind` or `pg_tde_rewind` with TDE"
    When TDE is enabled, using `pg_rewind` or `pg_tde_rewind` between diverged PostgreSQL nodes may corrupt encrypted relations.

    This happens because `pg_rewind` and `pg_tde_rewind` copy relation files between the data directories of two clusters. In some cases, only parts of files are replaced, leaving data encrypted with the internal encryption keys of the source cluster. This data cannot be decrypted by the destination cluster.
    
    For more information about how `pg_tde` manages internal encryption keys, see [How pg_tde works](how-does-tde-work.md) and [Encryption of data files](../faq.md#encryption-of-data-files).

    This behavior is inherited from `pg_rewind` and is currently a known issue in `pg_tde_rewind`.

    As a result, `pg_tde` may be unable to decrypt the copied data, causing queries to fail with errors such as:

    ```bash
    ERROR: 16 invalid pages among blocks 15..30 of relation "base/16384/16438"
    ```

## `pg_upgrade` and encrypted relations

!!! danger "`pg_upgrade` is not supported with `pg_tde`"
    PostgreSQL clusters that use `pg_tde` cannot currently be upgraded using `pg_upgrade`.

    The `pg_upgrade` tool does not properly handle the internal encryption keys used by `pg_tde`, which prevents the upgraded cluster from decrypting encrypted relations.

## Changing the database default tablespace

!!! warning "Changing the database default tablespace is not supported with `pg_tde`"
    Changing the default tablespace of a database is currently not supported when using `pg_tde`.

    This operation bypasses PostgreSQL's storage manager (SMGR), which is not supported by `pg_tde`.

    As a safeguard, `pg_tde` blocks the operation if encrypted objects are detected in the default tablespace.

    Objects located outside the default tablespace are not affected by this command.

## Currently unsupported WAL tools

The following tools are currently unsupported with `pg_tde` WAL encryption:

* `pg_createsubscriber`
* `pg_receivewal`
* `Barman`
* `pg_verifybackup` by default fails with checksum or WAL key size mismatch errors.
  As a workaround, use `-s` (skip checksum) and `-n` (`--no-parse-wal`) to verify backups.
* The asynchronous archiving feature of pgBackRest.

## Supported WAL tools

The following tools have been tested and verified by Percona to work with `pg_tde` WAL encryption:

* Patroni, for an example configuration see the following [Patroni configuration file](#example-patroni-configuration)
* `pg_tde_basebackup` (with `--wal-method=stream` or `--wal-method=none`), for details on using `pg_tde_basebackup` with WAL encryption, see [Backup with WAL encryption enabled](../how-to/backup-wal-enabled.md)
* `pg_tde_resetwal`
* `pg_tde_rewind`
* `pg_tde_upgrade`
* `pg_tde_waldump`
* pgBackRest (asynchronous archiving is NOT supported with encrypted WAL)

## Example Patroni configuration

The following is a Percona-tested example configuration.

??? example "Click to expand the Percona-tested Patroni configuration"
    ```yaml
    # Example Patroni configuration file maintained by Percona
    # Source: https://github.com/jobinau/pgscripts/blob/main/patroni/patroni.yml
    scope: tde
    name: pg1
    restapi:
      listen: 0.0.0.0:8008
      connect_address: pg1:8008
    etcd3:
      host: etcd1:2379
    bootstrap:
      dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576
        postgresql:
          use_pg_rewind: true
          use_slots: true
          parameters:
            archive_command: "/lib/postgresql/17/bin/pg_tde_archive_decrypt %f %p \"pgbackrest --stanza=tde archive-push %%p\""
            archive_timeout: 600s
            archive_mode: "on"
            logging_collector: "on"
            restore_command: "/lib/postgresql/17/bin/pg_tde_restore_encrypt %f %p \"pgbackrest --stanza=tde archive-get %%f \\\"%%p\\\"\""
          pg_hba:
            - local all all peer
            - host all all 0.0.0.0/0 scram-sha-256
            - host all all ::/0 scram-sha-256
            - local replication all peer
            - host replication all 0.0.0.0/0 scram-sha-256
            - host replication all ::/0 scram-sha-256
      initdb:
        - encoding: UTF8
        - data-checksums
        - set: shared_preload_libraries=pg_tde
      post_init: /usr/local/bin/setup_cluster.sh
    postgresql:
      listen: 0.0.0.0:5432
      connect_address: pg1:5432
      data_dir: /var/lib/postgresql/patroni-17
      bin_dir: /lib/postgresql/17/bin
      bin_name:
        pg_basebackup: pg_tde_basebackup
        pg_rewind: pg_tde_rewind
      pgpass: /var/lib/postgresql/patronipass
      authentication:
        replication:
          username: replicator
          password: rep-pass
        superuser:
          username: postgres
          password: secretpassword
      parameters:
        unix_socket_directories: /tmp
        # Use unix_socket_directories: /var/run/postgresql for Debian/Ubuntu distributions
    watchdog:
      mode: off
    tags:
      nofailover: false
      noloadbalance: false
      clonefrom: false
      nosync: false
    ```

!!! warning  
    The above example is Percona-tested, but Patroni versions differ, especially with discovery backends such as `etcd`. Ensure you adjust the configuration to match your environment, version, and security requirements.

## Next steps

Check which PostgreSQL versions and deployment types are compatible with `pg_tde` before planning your installation.

[View the versions and supported deployments :material-arrow-right:](supported-versions.md){.md-button}

Begin the installation process when you're ready to set up encryption.

[Start installing `pg_tde`](../install.md){.md-button}
