# Configure WAL encryption

The WAL encryption setup consists of three phases:

1. Register a global key provider
2. Create a server (principal) key using that provider
3. Enable WAL encryption and restart PostgreSQL

Follow the steps below to configure the server (principal) key for WAL before enabling encryption:

!!! note
    For a comprehensive list of supported `pg_tde` WAL encryption tools see [Limitations of pg_tde](index/tde-limitations.md).

1. Create the `pg_tde` extension if it does not exist:

    ```sql
    CREATE EXTENSION IF NOT EXISTS pg_tde;
    ```

2. Configure a global key provider

    Before creating the server (principal) key for WAL encryption, you must first configure a global key provider. See [Key management overview](global-key-provider-configuration/overview.md) for detailed instructions on configuring supported key providers.

3. Create the server (principal) key using the global key provider

    The server key (also referred to as the principal key) is the key used by PostgreSQL to encrypt WAL data. This key is created and stored through the configured global key provider.

    Run the following command to create the server key:

    ```sql
    SELECT pg_tde_set_server_key_using_global_key_provider(
            'server-key-name', 
            'provider-name'
    );
    ```

    Where:

    - `server-key-name` is the identifier for the server (principal) key
    - `provider-name` is the name of the previously configured global key provider

    This operation creates the server key in the key provider and associates it with the PostgreSQL instance.

4. Enable WAL level encryption using the `ALTER SYSTEM` command. You need the privileges of the superuser to run this command:

    ```sql
    ALTER SYSTEM SET pg_tde.wal_encrypt = on;
    ```

5. Restart the server to apply the changes.

    * On Debian and Ubuntu:

    ```sh
    sudo systemctl restart postgresql
    ```

    * On RHEL and derivatives

    ```sh
    sudo systemctl restart postgresql-<version>
    ```

6. (Optional) Verify that WAL encryption is enabled:

    ```sql
    SHOW pg_tde.wal_encrypt;
    ```

Now WAL files start to be encrypted for both encrypted and unencrypted tables.

For more technical references related to architecture, variables or functions, see:
[Technical Reference](advanced-topics/tech-reference.md){.md-button}

💬 Need help customizing this for your infrastructure? [Contact Percona support :octicons-link-external-16:](get-help.md)