# `pg_tde` documentation

`pg_tde` is the extension that brings in [Transparent Data Encryption (TDE)](tde.md) to PostgreSQL and enables users to keep sensitive data safe and secure. 

!!! important 

    This is the MVP version of the extension and is not meant for production use yet.

## What's encrypted

`pg_tde` encrypts the following:

* User data in tables, including TOAST tables, that are created using the extension. Metadata of those tables is not encrypted. 
* Write-Ahead Log (WAL) data for tables created using the extension 
* Temporary tables created during the database operation for data tables created using the extension

## What's not encrypted

In the MVP version of `pg_tde`, the following remains unencrypted:

* Indexes
* Logical replication
* `NULL` bitmaps of tuples
* Keys in the keyring file

Their encryption is planned for the next releases of `pg_tde`.

<i warning>:material-alert: Warning:</i> Note that introducing encryption/decryption affects performance. Our benchmark tests show less than 10% performance overhead.

[Get started](install.md){.md-button}

## Supported PostgreSQL versions

`pg_tde` is currently supported for Percona Distribution for PostgreSQL 16 and upstream PostgreSQL 16. 


## Useful links

* [What is Transparent Data Encryption](tde.md)

