# Encryption architecture

This section explains how `pg_tde` implements encryption inside PostgreSQL. It covers the key hierarchy, supported encryption algorithms, encryption workflow, and the core changes that make it possible to encrypt tables, WAL, and other database files.
  
Together, these components form the foundation of data-at-rest encryption in `pg_tde`.

## Two-key hierarchy

`pg_tde` uses two kinds of keys for encryption:

1. Internal keys to encrypt the data. They are stored in PostgreSQL's data directory under `$PGDATA/pg_tde`
2. Principal keys, which encrypt internal keys, are stored externally in a Key Management System (KMS) using the key provider API

`pg_tde` uses one principal key per database. Every internal key for the given database is encrypted using this principal key.

Internal keys are used for specific database files: each file with a different [Object Identifier (OID) :octicons-link-external-16:](https://www.postgresql.org/docs/current/datatype-oid.html) has a different internal key.

**Example:**

A table with 4 indexes will have at least 5 internal keys, one for the table and one for each index. Additional associated relations, such as sequences or a TOAST table, also have their own keys.

## Encryption algorithm

`pg_tde` currently uses the following encryption algorithms:

* `AES-128-CBC` for encrypting database files; encrypted with internal keys
* `AES-128-CTR` for WAL encryption; encrypted with internal keys
* `AES-128-GCM` for encrypting internal keys; encrypted with the principal key

## Encryption workflow

You can use `pg_tde` to encrypt entire databases or only selected tables.

To support this without metadata changes, encrypted tables are labeled with the `tde_heap` access method marker.

The `tde_heap` access method is functionally identical to the `heap` access method. This allows `pg_tde` to distinguish between encrypted (`tde_heap`)  and non-encrypted (`heap`) tables.

The initial decision about encryption is made using the `postgres` event trigger mechanism:

* When the `tde_heap` clause is used for `CREATE TABLE` or `ALTER TABLE` statements, then the newly created data files are marked as encrypted
* After this, the file operations encrypt or decrypt the data

Subsequent decisions are done using a slightly modified Storage Manager (SMGR) API:

* When a database file is re-created with a different ID as a result of a `TRUNCATE` or a `VACUUM FULL` command, the newly created file inherits the encryption information
* The file is then either encrypted or left unencrypted based on that inheritance

## WAL encryption functionality

You can control WAL encryption globally via the [`pg_tde.wal_encrypt`](../variables.md#pg_tdewal_encrypt) GUC variable, which requires a server restart.

WAL keys also contain the [LSN :octicons-link-external-16:](https://www.postgresql.org/docs/17/wal-internals.html) of the first WAL write after key creation. This allows `pg_tde` to know which WAL ranges are encrypted or not and with which key.

!!! note
    See the [Configure WAL encryption](../wal-encryption.md) chapter for more information.

The setting only controls writes so that only WAL writes are encrypted when WAL encryption is enabled. This means that WAL files can contain both encrypted and unencrypted data, depending on what the status of this variable was when writing the data.

`pg_tde` keeps track of the encryption status of WAL records using internal keys. When the server is restarted it writes a new internal key if WAL encryption is enabled, or if it is disabled and was previously enabled it writes a dummy key signaling that WAL encryption ended.

With this information the WAL reader code can decide if a specific WAL record has to be decrypted or not and which key it should use to decrypt it.

## Encrypting other access methods

Currently `pg_tde` only encrypts `heap` tables and other files such as indexes, TOAST tables, sequences that are related to the `heap` tables.

Indexes include any kind of index that goes through the SMGR API, not just the built-in indexes in PostgreSQL.

Other table access methods that use the SMGR API could also be encrypted. This requires adding a marker access method and extending the event triggers, using the same approach as with `heap` tables.

## Storage Manager (SMGR) API

`pg_tde` relies on a slightly modified version of the SMGR API. These modifications include:

* Making the API generally extensible, where extensions can inject custom code into the storage manager
* Adding tracking information for files. When a new file is created for an existing relation, references to the existing file are also passed to the SMGR functions

With these modifications, `pg_tde` implements an additional layer on top of the normal Magnetic Disk SMGR API: if the related table is encrypted, `pg_tde` encrypts a file before writing it to the disk and, similarly, decrypts it after reading when needed.

## WAL encryption

WAL encryption is implemented through a separate, server-wide mechanism that extends PostgreSQL WAL-related APIs. Like the SMGR changes described above, this required additional core API extensions. For details, see [Configure WAL encryption](../wal-encryption.md).
