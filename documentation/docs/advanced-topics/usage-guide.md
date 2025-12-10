# Usage guide

This guide shows how to use `pg_tde` in practice. It walks you through setting up `pg_tde`, adding and managing key providers, creating and rotating keys, setting permissions, and encrypting tables.  

Use this section as a step-by-step reference when deploying or operating `pg_tde` in your PostgreSQL environment.

## Set up pg_tde

To get started with `pg_tde`, follow these steps:

* Add `pg_tde` to the `shared_preload_libraries` in `postgresql.conf` as this is required for the SMGR extensions
* Execute `CREATE EXTENSION pg_tde` in the databases where they want to use encryption
* Optionally, enable `pg_tde.wal_encrypt` in `postgresql.conf` to encrypt WAL writes
* Optionally, disable `pg_tde.inherit_global_providers` in `postgresql.conf` (it is enabled by default)

## Add providers

You can add keyring providers to either the global or database specific scope.

If `pg_tde.inherit_global_providers` is `on`, global providers are visible for all databases, and can be used.
If `pg_tde.inherit_global_providers` is `off`, global providers are only used for WAL encryption.

To add a global provider:

```sql
pg_tde_add_global_key_provider_<TYPE>('provider_name', ... details ...)
```

To add a database specific provider:

```sql
pg_tde_add_database_key_provider_<TYPE>('provider_name', ... details ...)
```

## Change providers

To change a value of a global provider:

```sql
pg_tde_change_global_key_provider_<TYPE>('provider_name', ... details ...)
```

To change a value of a database specific provider:

```sql
pg_tde_change_database_key_provider_<TYPE>('provider_name', ... details ...)
```

These functions also allow changing the type of a provider but **do not** migrate any data. They are expected to be used during infrastructure migration, for example when the address of a server changes.

## Change providers from the command line

To change a provider from a command line, `pg_tde` provides the `pg_tde_change_key_provider` command line tool.

This tool work similarly to the above functions, with the following syntax:

```sh
pg_tde_change_key_provider <dbOid> <providerType> ... details ...
```

!!! note
    Since this tool is expected to be offline, it bypasses all permission checks. This is also the reason why it requires a `dbOid` instead of a name, as it has no way to process the catalog and look up names.

    This tool does not validate any parameters.

## Delete providers

Providers can be deleted by using the following functions:

```sql
pg_tde_delete_database_key_provider(provider_name)
pg_tde_delete_global_key_provider(provider_name)
```

For database specific providers, the function first checks if the provider is used or not, and the provider is only deleted if it's not used.

For global providers, the function checks if the provider is used anywhere, WAL or any specific database, and returns an error if it is.

## List/query providers

`pg_tde` provides 2 functions to show providers:

* `pg_tde_list_all_database_key_providers()`
* `pg_tde_list_all_global_key_providers()`

These functions return a list of provider names, type and configuration.

## Provider permissions

`pg_tde` implements access control based on execution rights on the administration functions.

For keys and providers administration, it provides two pair of functions:

```sql
pg_tde_GRANT_database_key_management_TO_role
pg_tde_REVOKE_database_key_management_FROM_role
```

## Create and rotate keys

Principal keys can be created using the following functions:

```sql
pg_tde_create_key_using_(global/database)_key_provider('key-name', 'provider-name')
```

Principal keys can be used or rotated using the following functions:

```sql
pg_tde_set_key_using_(global/database)_key_provider('key-name', 'provider-name')
pg_tde_set_server_key_using_(global/database)_key_provider('key-name', 'provider-name')
pg_tde_set_default_key_using_(global/database)_key_provider('key-name', 'provider-name')
```

## Default principal key

With `pg_tde.inherit_global_key_providers`, it is also possible to set up a default global principal key, which will be used by any database which has the `pg_tde` extension enabled, but doesn't have a database specific principal key configured using `pg_tde_set_key_using_(global/database)_key_provider`.

With this feature, it is possible for the entire database server to easily use the same principal key for all databases, completely disabling multi-tenancy.

### Manage a default key

You can manage a default key with the following functions:

* `pg_tde_create_key_using_global_key_provider('key-name','provider-name')`
* `pg_tde_set_default_key_using_global_key_provider('key-name','provider-name')`
* `pg_tde_delete_default_key()`

!!! note
    `pg_tde_delete_default_key()` is only possible if there's no database currently using the default principal key.
    Changing the default principal key will rotate the encryption of internal keys for all databases using the current default principal key.

### Delete a key

The `pg_tde_delete_key()` function unsets the principal key for the current database. If the current database has any encrypted tables, and there isn’t a default principal key configured, it reports an error instead. If there are encrypted tables, but there’s also a default principal key, internal keys will be encrypted with the default key.

!!! note
    WAL keys **cannot** be unset, as server keys are managed separately.

## Current key details

`pg_tde_key_info()` returns the name of the current principal key, and the provider it uses.

`pg_tde_server_key_info()` does the same for the server key.

`pg_tde_default_key_info()` does the same for the default key.

`pg_tde_verify_key()` checks that the key provider is accessible, that the current principal key can be downloaded from it, and that it is the same as the current key stored in memory - if any of these fail, it reports an appropriate error.

## Key permissions

Users with management permissions to a specific database `(pg_tde_(grant/revoke)_(global/databse)_key_management_(to/from)_role)` can change the keys for the database, and use the current key functions. This includes creating keys using global providers, if `pg_tde.inherit_global_providers` is enabled.

Also the `pg_tde_(grant/revoke)_database_key_management_to_role` function deals with only the specific permission for the above function: it allows a user to change the key for the database, but not to modify the provider configuration.

## Create an encrypted table

To create an encrypted table, use the following command:

```sql
CREATE TABLE t1(a INT) USING tde_heap;
```

## Alter an encrypted table

To alter or modify an encrypted table, use the following command:

```sql
ALTER TABLE t1 SET ACCESS METHOD tde_heap;
```

## Change the pg_tde.inherit_global_keys setting

It is possible to use `pg_tde` with `inherit_global_keys = on`, refer to the global keys or keyrings in databases, and then change this setting to `off`.

In this case, existing references to global providers or the global default principal key keep working as before, but new references to the global scope cannot be made.
