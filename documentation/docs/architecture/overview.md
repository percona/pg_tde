# Architecture overview

`pg_tde` is a **customizable, complete, data at rest encryption extension**. Extension means that `pg_tde` is delivered as a PostgreSQL extension.

!!! note
    `pg_tde` relies on extensibility changes in the PostgreSQL core. It currently runs only with [Percona Server for PostgreSQL :octicons-link-external-16:](https://docs.percona.com/postgresql/17/index.html), which includes those changes.

The following sections break down the key architectural components of this design.

**a. Customizable** means that `pg_tde` supports many different use cases:

* Encrypting all tables in all databases, or only selected ones
* Storing encryption keys in different external key storage servers, for a list of these see [Key management overview](../global-key-provider-configuration/overview.md)
* Using a single key for a clusters, or different keys for different clusters
* Centralizing all keys in one provider, or splitting them across providers
* Controlling permissions: who manages keys and who can create encrypted or unencrypted tables

**b. Complete** means that `pg_tde` aims to encrypt data at rest.

**c. Data at rest** means everything written to the disk. This includes the following:

* Table data files
* Indexes
* Sequences
* Temporary tables
* Write Ahead Log (WAL)

## Main components

The main components of `pg_tde` are:

* **Core server changes** focus on making the server more extensible, allowing the main logic of `pg_tde` to remain separate, as an extension. Core changes also add encryption-awareness to some command line tools that have to work directly with encrypted tables or encrypted WAL files. 

    You can find the source code [here :octicons-link-external-16:](https://github.com/percona/postgres/tree/{{tdebranch}}).

* The **`pg_tde` extension** implements the encryption code by hooking into the extension points introduced in the core changes, and the already existing extension points in the PostgreSQL server.

    Everything is controllable with GUC variables and SQL statements, similar to other extensions.

* The **keyring API and libraries** implement the key storage logic with different key providers. The API is internal only, the keyring the libraries are currently part of the main codebase but could be separated into shared libraries in the future.
