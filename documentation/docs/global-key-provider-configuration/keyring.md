# Keyring file configuration

This setup is intended for development and stores the keys, unencrypted, in a data file you specify.

!!! note
     While keyring files may be acceptable for **local** or **testing environments**, proper [KMS providers](../global-key-provider-configuration/overview.md) are the recommended approach for production deployments.

You can configure key providers either at the database level (for development and testing) or at the global level (for production).

The steps below provide an example on how to add a [database-scoped key provider](../functions.md#add-or-modify-local-key-file-providers):

1. Create a database-scoped file key provider (`file-keyring` in this example) in the `/tmp/pg_tde_test_local_keyring.per` file:

    ```sql
    SELECT pg_tde_add_database_key_provider_file(
        'file-keyring',
        '/tmp/pg_tde_test_local_keyring.per'
    );
    ```

2. Create a key (`my_default_key` in this example) inside the newly created `file-keyring` provider:

    ```sql
    SELECT pg_tde_create_key_using_database_key_provider(
        'my_default_key',
        'file-keyring'
    );
    ```

3. Set the key (`my_default_key`) from the key provider (`file-keyring`):

    ```sql
    SELECT pg_tde_set_key_using_database_key_provider(
        'my_default_key',
        'file-keyring'
    );
    ```

    !!! tip
        You can check the default key information (such as the date and time of creation). Run:

        ```sql
        SELECT pg_tde_default_key_info();
        ```

4. Now, create a table using [tde_heap](../index/table-access-method.md#how-tde_heap-works-with-pg_tde):

    ```sql
    CREATE TABLE customer_table (a INT) USING tde_heap;
    ```

    The newly created table is encrypted with the default key you have set (`my_default_key`).

    !!! tip
        To check if your created table is encrypted with tde_heap, run:

        ```sql
        \d+ test1
        ```

        If `Access method: tde_heap`, then your table is encrypted.

        ??? "Example output"
                postgres=# \d+ test1
                                                    Table "public.test1"
                Column |  Type   | Collation | Nullable | Default | Storage | Compression | Stats target | Description
                --------+---------+-----------+----------+---------+---------+-------------+--------------+-------------
                a      | integer |           |          |         | plain   |             |              |
                Access method: tde_heap

## Further reading

Next, for production deployments, [configure a global principal key](set-principal-key.md) using a proper [KMS provider](../global-key-provider-configuration/overview.md).

Alternatively, you can skip directly to [validating encryption with pg_tde](../test.md) or [configuring WAL encryption](../wal-encryption.md).

You can also review the available `pg_tde` functions in [Functions](../functions.md).
