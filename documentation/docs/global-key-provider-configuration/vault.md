# Vault configuration

You can configure `pg_tde` to use HashiCorp Vault as a global key provider for managing encryption keys securely. Both the open source and enterprise editions are supported.

## Configure Vault with pg_tde in Docker

This example setup describes how to run HashiCorp Vault and Percona PostgreSQL with `pg_tde` side by side using Docker, configure Vault policies, and connect it as a global key provider for TDE encryption.

!!! note
    For production deployments, follow your organization’s security standards.

### 1. Create the docker-compose.yaml file

The following `docker-compose.yaml` file is an example on how to run both Vault and PostgreSQL with a shared secrets volume:

??? example "docker-compose.yaml (example file)"

    ```bash
    version: '3.8'

    services:
    vault:
        image: hashicorp/vault:latest
        container_name: vault
        ports:
        - "8200:8200"
        volumes:
        - ./vault-config.hcl:/vault/config/vault-config.hcl
        - ./vault-data:/vault/data
        - shared-secrets:/vault/secrets
        environment:
        VAULT_ADDR: http://127.0.0.1:8200
        command: vault server -config=/vault/config/vault-config.hcl

    pg:
        image: percona/percona-distribution-postgresql:17.5-2
        container_name: pg
        ports:
        - "5432:5432"
        environment:
        POSTGRES_PASSWORD: secret
        ENABLE_PG_TDE: "1"
        volumes:
        - ./pgdata:/var/lib/postgresql/data
        - shared-secrets:/etc/postgresql/secrets:ro
        depends_on:
        - vault

    volumes:
    shared-secrets:
    ```

### 2. Enable the KV v2 secrets engine

In the Vault container, enable a KV v2 storage engine for `pg_tde`:

```bash
vault secrets enable -path=tde -version=2 kv
```

This creates a `tde/` mount for storing encrypted keys.

!!! note "Vault namespaces (Enterprise) and mounts"
    If you are using **Vault Enterprise namespaces**, you don’t need a separate
    namespace parameter when configuring `pg_tde`.

    You can include the namespace directly in the mount path. For example:

    ```sql
    SELECT pg_tde_add_global_key_provider_vault_v2(
        'vault-ns',
        'https://127.0.0.1:8200',
        'pgns/tde/data/global-key',
        '/etc/postgresql/secrets/vault_token.txt',
        NULL
    );
    ```

    This is equivalent to configuring a namespace separately and works with both:

    * Vault OSS  
    * Vault Enterprise (with namespaces)

    Using the full path (`namespace/mount/...`) is the recommended approach.

### 3. Create a Vault policy for pg_tde

Define a Vault policy that grants `pg_tde` access to read, write, and list keys.

```bash
vault policy write tde-policy - <<EOF
path "tde/data/*" {
  capabilities = ["read", "create", "update", "list"]
}

path "tde/metadata/*" {
  capabilities = ["read", "list"]
}
EOF
```

This allows `pg_tde` to:

- read, create, and update encryption keys
- list and access metadata for the `tde/` path

!!! tip

    If you encounter the following error:

    ```sql
    ERROR: failed to get mount info for "http://vault:8200" at mountpoint ...
    ```

    Ensure your Vault policy includes the following path:

    ```ini
    path "sys/mounts/*" {
      capabilities = ["read"]
    }
    ```

    This allows `pg_tde` to read the mount metadata from Vault.

### 4. Create an Authentication Method and Token

Enable the AppRole authentication method:

```bash
vault auth enable approle
vault write auth/approle/role/tde-role policies="tde-policy"
```

Generate a token associated with the tde-policy:

```bash
vault token create -policy="tde-policy"
```

Example output:

```css
Key                  Value
token                hvs.{secret_code}
token_policies       ["default" "tde-policy"]
```

### 5. Share the token with PostgreSQL

Copy the generated token into the shared secrets directory (shared secrets volume) so PostgreSQL can use it:

```bash
echo "hvs.secret_code" > /vault/secrets/vault_token.txt
```

!!! tip
    You can access this file in PostgreSQL at `/etc/postgresql/secrets/vault_token.txt`.

### 6. Register Vault as a global key provider in PostgreSQL

In the PostgreSQL container, connect `pg_tde` to Vault using:

```sql
SELECT pg_tde_add_global_key_provider_vault_v2(
  'vault-provider',
  'http://vault:8200',
  'tde/data/global-key',
  '/etc/postgresql/secrets/vault_token.txt',
  NULL
);
```

### 7. Create and set the global master key

Create the global master key:

```sql
SELECT pg_tde_create_key_using_global_key_provider(
  'global-master-key',
  'vault-provider'
);
```

Then set it:

```sql
SELECT pg_tde_set_default_key_using_global_key_provider(
  'global-master-key',
  'vault-provider'
);
```

### 8. Test encryption with a sample table

Create a sample table:

```sql
CREATE TABLE secure_data (
  id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT,
  amount NUMERIC(10,2),
  created_at DATE
) USING tde_heap;
```

Then insert data into the table:

```sql
INSERT INTO secure_data (name, amount, created_at) VALUES
('Alice', 1234.56, '2025-08-01'),
('Bob', 7890.12, '2025-08-10'),
('Charlie', 345.67, '2025-08-19');
```

Query the table and confirm that the encryption is functioning:

```sql
select * from secure_data;
 id |  name   | amount  | created_at
----+---------+---------+------------
  1 | Alice   | 1234.56 | 2025-08-01
  2 | Bob     | 7890.12 | 2025-08-10
  3 | Charlie |  345.67 | 2025-08-19
(3 rows)
```

## Example global key provider usage

```sql
SELECT pg_tde_add_global_key_provider_vault_v2(
    'provider-name',
    'url',
    'mount',
    'secret_token_path',
    'ca_path'
);
```

## Parameter descriptions

* `provider-name` is the name to identify this key provider
* `secret_token_path` is a path to the file that contains an access token with read and write access to the above mount point
* `url` is the URL of the Vault server
* `mount` is the mount point where the keyring should store the keys
* [optional] `ca_path` is the path of the CA file used for SSL verification

The following example is for testing purposes only. Use secure tokens and proper SSL validation in production environments:

```sql
SELECT pg_tde_add_global_key_provider_vault_v2(
    'my-vault',
    'https://vault.vault.svc.cluster.local:8200',
    'secret/data',
    '/path/to/token_file',
    '/path/to/ca_cert.pem'
);
```

For more information on related functions, see [Function Reference](../functions.md).

## Required permissions

The PostgreSQL instance requires the following Vault API capabilities to manage and read encryption keys:

* `sys/mounts/<mount>/*` - **read** permissions
* `<mount>/data/*` - **create**, **read** permissions
* `<mount>/metadata/*` - **list** permissions

!!! note
    For more information on Vault permissions, see the [following documentation](https://developer.hashicorp.com/vault/docs/concepts/policies).

## Next steps

[Global Principal Key Configuration :material-arrow-right:](set-principal-key.md){.md-button}
