# FAQ

## Why do I need TDE?

- Compliance to security and legal regulations like General Data Protection Regulation (GDPR), Payment Card Industry Data Security Standard (PCI DSS), California Consumer Privacy Act (CCPA), Data Protection Act 2018 (DPA 2018) and others
- Encryption of backups. Even when an authorized person gets physical access to a backup, encryption ensures that the data remains unreadable and secure.
- Granular encryption of specific data sets and reducing the performance overhead that encryption brings. 
- Additional layer of security to existing security measures

## When and how should I use TDE?

If you are dealing with Personally Identifiable Information (PII), data encryption is crucial. Especially if you are involved in areas like with strict regulations like:

* financial services where TDE helps to comply with PCI DSS, 
* healthcare and insurance - compliance with HIPAA, 
* telecommunications, government and education to ensure data confidentiality.

Using TDE helps you avoid the following risks:

* Data breaches
* Identity theft that may lead to financial fraud and other crimes
* Reputation damage leading to loss of customer trust and business
* Legal consequences and financial losses for non-compliance with data protection regulations
* Internal threats by misusing unencrypted sensitive data 

If to translate sensitive data to files stored in your database, these are user data in tables, temporary files, WAL files. TDE has you covered encrypting all these files.


## I use disk-level encryption. Why should I care about TDE?

Encrypting a hard drive encrypts all data including system and application files that are there. However, disk encryption doesn’t protect your data after the boot-up of your system. During runtime, the files are decrypted with disk-encryption.

TDE focuses specifically on data files and offers a more granular control over encrypted data. It also ensures that files are encrypted on disk during runtime and when moved to another system or storage.

Consider using TDE and storage-level encryption together to add another layer of data security.

## Is TDE enough to ensure data security?

No. TDE is an additional layer to ensure data security. It protects data at rest. Consider introducing also these measures:

* Access control and authentication
* Strong network security like TLS
* Disk encryption
* Regular monitoring and auditing
* Additional data protection for sensitive fields (e.g., application-layer encryption)

## How does `pg_tde` make my data safe?

`pg_tde` uses two keys to encrypt data:

* Internal encryption keys to encrypt the data. These keys are stored internally, in a single `$PGDATA/pg_tde` directory.
* Principal keys to encrypt table encryption keys. These keys are stored externally, in the Key Management Store (KMS). You can use either the HashiCorp Vault server or the KMIP-compatible server.

Here’s how encryption works:

First, data files are encrypted with internal keys. Each file that has a different OID, has an internal key. For example, a table with 4 indexes will have 5 internal keys - one for the table and one for each index.	

The initial decision on what file to encrypt is based on the PostgreSQL triggers. When you run a `CREATE` or `ALTER TABLE` statement with the `USING tde_heap` clause, the newly created data files are marked as encrypted, and then file operations encrypt/decrypt the data. Later, if an initial file is re-created as a result of a `TRUNCATE` or `VACUUM FULL` command, the newly created file inherits the encryption information and is either encrypted or not. 

The principal key is used to encrypt the internal keys. The principal key is stored in the key management store. When you query the table, the principal key is retrieved from the key store to decrypt the table. Then the internal key for that table is used to decrypt the data.

## Should I encrypt all my data?

It depends on your business requirements and the sensitivity of your data. Encrypting all data is a good practice but it can have a performance impact. 

Consider encrypting only tables that store sensitive data. `pg_tde` supports multi-tenancy enabling you to do just that. You can decide what tables to encrypt and with what key. The [Setup](setup.md) section in documentation focuses on this approach.

We advise encrypting the whole database only if all your data is sensitive, like PII, or if there is no other way to comply with data safety requirements. See [How to configure global encryption](global-encryption.md).

## What cipher mechanisms are used by `pg_tde`?

`pg_tde` currently uses a AES-CBC-128 algorithm. First the internal keys in the datafile are encrypted using the principal key with AES-CBC-128, then the file data itself is again encrypted using AES-CBC-128 with the internal key.

For WAL encryption, AES-CTR-128 is used.

The support of other encryption mechanisms such as AES256 is planned for future releases.

## Is post-quantum encryption supported?

No, it's not yet supported.

## Can I encrypt an existing table?

Yes, you can encrypt an existing table. Run the ALTER TABLE command as follows:

```
ALTER TABLE table_name SET access method tde_heap;
```

## Do I have to restart the database to encrypt the data?

No, you don't have to restart the database to encrypt the data. When you create or alter the table using the `tde_heap` access method, the files are marked as those that require encryption. The encryption happens at the storage manager level, before a transaction is written to disk. Read more about how `tde_heap` access method works in the [How tde_heap works](table-access-method.md#how-tde_heap-works) section.

## What happens to my data if I lose a principal key?

If you lose encryption keys, especially, the principal key, the data is lost. That's why it's critical to back up your encryption keys securely.

## Can I use `pg_tde` in a multi-tenant setup?

Multi-tenancy is the type of architecture where multiple users, or tenants, share the same resource. It can be a database, a schema or an entire cluster. 

In `pg_tde`, multi-tenancy is supported via a separate principal key per database. This means that a database owner can decide what tables to encrypt within a database. The same database can have both encrypted and non-encrypted tables.

To control user access to the databases, you can use role-based access control (RBAC).

## Are my backups safe? Can I restore from them?

`pg_tde` encrypts data at rest. This means that data is stored on disk in an encrypted form. During a backup, already encrypted data files are copied from disk onto the storage. This ensures the data safety in backups.

Since the encryption happens on the database level, it makes no difference for your tools and applications. They work with the data in the same way.

To restore from an encrypted backup, you must have the same principal encryption key, which was used to encrypt files in your backup.  

## I'm using the FIPS mode. Am I safe to use it and `pg_tde`? Can I use my own OpenSSL library in the FIPS mode and `pg_tde` together?

Yes. `pg_tde` works with the FIPS-compliant version of OpenSSL regardless if it is supplied within your operating system or if you use your own OpenSSL libraries. In the latter case, ensure that your OpenSSL libraries are FIPS certified. 
