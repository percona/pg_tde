# Setup

Load the `pg_tde` at the start time. The extension requires additional shared memory; therefore,  add the `pg_tde` value for the `shared_preload_libraries` parameter and restart the `postgresql` instance.

1. Use the [ALTER SYSTEM](https://www.postgresql.org/docs/current/sql-altersystem.html) command from `psql` terminal to modify the `shared_preload_libraries` parameter.

    ```sql
    ALTER SYSTEM SET shared_preload_libraries = 'pg_tde';
    ```

2. Start or restart the `postgresql` instance to apply the changes.

    * On Debian and Ubuntu:    

       ```sh
       sudo systemctl restart postgresql.service
       ```
    
    * On RHEL and derivatives

       ```sh
       sudo systemctl restart postgresql-16
       ```

3. Create the extension using the [CREATE EXTENSION](https://www.postgresql.org/docs/current/sql-createextension.html) command. You must have the privileges of a superuser or a database owner to use this command. Connect to `psql` as a superuser for a database and run the following command:

    ```sql
    CREATE EXTENSION pg_tde;
    ```
    
    By default, the `pg_tde` extension is created for the `postgres` database or the database which your user owns. To encrypt the data in other databases, you must explicitly run the `CREATE EXTENSION` command for them. 

    !!! tip

        You can have the `pg_tde` extension automatically enabled for every newly created database. Modify the template `template1` database as follows: 

        ```
        psql -d template1 -c 'CREATE EXTENSION pg_tde;'
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

## Keyring configuration

```json
{
        'provider': 'file',
        'datafile': '/tmp/pgkeyring',
}
```

Currently the keyring configuration only supports the file provider, with a single datafile parameter.

This datafile is created and managed by PostgreSQL, the only requirement is that `postgres` should be able to write to the specified path.

This setup is intended for development, and stores the keys unencrypted in the specified data file.