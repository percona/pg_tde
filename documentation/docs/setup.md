# Set up `pg_tde`

## Enable extension

Load the `pg_tde` at the start time. The extension requires additional shared memory; therefore,  add the `pg_tde` value for the `shared_preload_libraries` parameter and restart the `postgresql` instance.

1. Use the [ALTER SYSTEM](https://www.postgresql.org/docs/current/sql-altersystem.html) command from `psql` terminal to modify the `shared_preload_libraries` parameter.

    ```
    ALTER SYSTEM SET shared_preload_libraries = 'pg_tde';
    ```

2. Start or restart the `postgresql` instance to apply the changes.

    * On Debian and Ubuntu:    

       ```{.bash data-prompt="$"}
       $ sudo systemctl restart postgresql.service
       ```
    
    * On RHEL and derivatives

       ```{.bash data-prompt="$"}
       $ sudo systemctl restart postgresql-17
       ```

3. Create the extension using the [CREATE EXTENSION](https://www.postgresql.org/docs/current/sql-createextension.html) command. You must have the privileges of a superuser or a database owner to use this command. Connect to `psql` as a superuser for a database and run the following command:

    ```
    CREATE EXTENSION pg_tde;
    ```
    
    By default, the `pg_tde` extension is created for the currently used database. To enable data encryption in other databases, you must explicitly run the `CREATE EXTENSION` command against them. 

    !!! tip

        You can have the `pg_tde` extension automatically enabled for every newly created database. Modify the template `template1` database as follows: 

        ```
        psql -d template1 -c 'CREATE EXTENSION pg_tde;'
        ```

## Key provider configuration

1. Set up a key provider for the database where you have enabled the extension.

    === "With HashiCorp Vault"

        The Vault server setup is out of scope of this document.

        ```
        SELECT pg_tde_add_key_provider_vault_v2('provider-name',:'secret_token','url','mount','ca_path');
        ``` 

        where: 

        * `url` is the URL of the Vault server
        * `mount` is the mount point where the keyring should store the keys
        * `secret_token` is an access token with read and write access to the above mount point
        * [optional] `ca_path` is the path of the CA file used for SSL verification


    === "With keyring file"

        This setup is intended for development and stores the keys unencrypted in the specified data file.    

        ```
        SELECT pg_tde_add_key_provider_file('provider-name','/path/to/the/keyring/data.file');
        ```

	<i warning>:material-information: Warning:</i> This example is for testing purposes only:

	```
	SELECT pg_tde_add_key_provider_file('file-vault','/tmp/pg_tde_test_local_keyring.per');
	```
       
       
2. Add a principal key

    ```
    SELECT pg_tde_set_principal_key('name-of-the-principal-key', 'provider-name');
    ```

    <i warning>:material-information: Warning:</i> This example is for testing purposes only:

    ```
    SELECT pg_tde_set_principal_key('test-db-master-key','file-vault');
    ```

    The key is auto-generated.

   <i info>:material-information: Info:</i> The key provider configuration is stored in the database catalog in an unencrypted table. See [how to use external reference to parameters](external-parameters.md) to add an extra security layer to your setup.


## WAL encryption configuration (tech preview)

After you [enabled `pg_tde`](#enable-extension) and started the Percona Server for PostgreSQL, a principal key and internal keys for WAL encryption are created. They are stored in the data directory so that after WAL encryption is enabled, any process that requires access to WAL (a recovery or a checkpointer) can use them for decryption.

Now you need to instruct `pg_tde ` to encrypt WAL files by configuring WAL encryption. Here's how to do it:

### Enable WAL level encryption

1.  Use the `ALTER SYSTEM SET` command. You need the privileges of the superuser to run this command:

    ```
    ALTER SYSTEM set pg_tde.wal_encrypt = on;
    ```

2. Restart the server to apply the changes.

    * On Debian and Ubuntu:    

       ```{.bash data-prompt="$"}
       $ sudo systemctl restart postgresql.service
       ```
    
    * On RHEL and derivatives

       ```{.bash data-prompt="$"}
       $ sudo systemctl restart postgresql-17
       ```

On the server start 

### Rotate the principal key

We highly recommend you to create your own keyring and rotate the principal key. This is because the default principal key is created from the local keyfile and is stored unencrypted. 

Rotating the principal key means re-encrypting internal keys used for WAL encryption with the new principal key. This process doesn't stop the database operation meaning that reads and writes can take place as usual during key rotation. 

1. Set up the key provider for WAL encryption

    === "With HashiCorp Vault"
    
        ```
        SELECT pg_tde_add_key_provider_vault_v2('PG_TDE_GLOBAL','provider-name',:'secret_token','url','mount','ca_path');
        ``` 

        where: 

        * `PG_TDE_GLOBAL` is the constant that defines the WAL encryption key  
        * `provider-name` is the name you define for the key provider
        * `url` is the URL of the Vault server
        * `mount` is the mount point where the keyring should store the keys
        * `secret_token` is an access token with read and write access to the above mount point
        * [optional] `ca_path` is the path of the CA file used for SSL verification


    === "With keyring file"

        This setup is intended for development and stores the keys unencrypted in the specified data file.    

        ```
        SELECT pg_tde_add_key_provider_file('provider-name','/path/to/the/keyring/data.file');
        ```

2. Rotate the principal key. Don't forget to specify the `PG_TDE_GLOBAL` constant to rotate only the principal key for WAL.

    ```
    SELECT pg_tde_rotate_principal_key('PG_TDE_GLOBAL', 'new-principal-key', 'provider-name');
    ```

    Now all WAL files are encrypted for both encrypted and unencrypted tables. 
   
3. Verify the encryption by checking the `pg_tde.wal_encrypt` GUC (Grand Unified Configuration) parameter as follows: 

    ```
    SELECT name, setting FROM pg_settings WHERE name = 'pg_tde.wal_encrypt';
    ```

    ??? example "Sample output"

        ```{.text .no-copy}

                name        | setting
        --------------------+---------
         pg_tde.wal_encrypt | on
        ```

## Next steps

[Test TDE](test.md){.md-button}
 
