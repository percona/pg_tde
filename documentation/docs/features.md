# Features

We provide `pg_tde` in two versions for both PostgreSQL Community and [Percona Server for PostgreSQL](https://docs.percona.com/postgresql/17/). The difference between the versions is in the set of included features which in its turn depends on the Storage Manager API. While PostgreSQL Community uses the default Storage Manager API, Percona Server for PostgreSQL extends the Storage Manager API enabling to integrate custom storage managers.

The following table provides features available for each version:

| PostgreSQL Community version  | Percona Server for PostgreSQL version <br> |
|----------------------|-------------------------------|
| Table encryption: <br> - data tables, <br> - TOAST tables <br> - temporary tables created during the database operation.<br><br> Metadata of those tables is not encrypted. | Table encryption: <br> - data tables, <br> - TOAST tables <br> - temporary tables created during the database operation.<br> - Index data for encrypted tables<br><br> Metadata of those tables is not encrypted.  |
| Write-Ahead Log (WAL) encryption of data in encrypted tables | Write-Ahead Log (WAL) encryption of data for encrypted and non-encrypted tables  |
| Multi-tenancy support| Multi-tenancy support |
|                      | Global principal key management | 
| Table-level granularity |Table-level granularity | 
| Key management via: <br> - HashiCorp Vault; <br> - Local keyfile | Key management via: <br> - HashiCorp Vault; <br> - KMIP server; <br> - Local keyfile|
| | Logical replication of encrypted tables | 


<i warning>:material-alert: Warning:</i> Note that introducing encryption/decryption affects performance. Our benchmark tests show less than 10% performance overhead for most situations. However, in some specific applications such as those using JSONB operations, performance degradation might be higher.

[Get started](install.md){.md-button}