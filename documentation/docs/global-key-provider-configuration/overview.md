# Key management overview

In production environments, storing encryption keys locally on the PostgreSQL server can introduce security risks. To enhance security, `pg_tde` supports integration with external Key Management Systems (KMS) through a Global Key Provider interface.

This section describes how you can configure `pg_tde` to use the local and external key providers.

To use an external KMS with `pg_tde`:

1. Configure a Key Provider
2. Set the [Global Principal Key](set-principal-key.md)

!!! note
    While key files may be acceptable for **local** or **testing environments**, KMS integration is the recommended approach for production deployments.

!!! important
    When using HashiCorp Vault, **KV v2 is the recommended and supported integration method**.

    The KMIP engine in Vault is not a validated configuration for `pg_tde` and is not recommended for production deployments.

!!! warning
    Do not rotate encryption keys while a backup is running. This may result in an inconsistent backup and restore failure. This applies to all backup tools.

    Schedule key rotations outside backup windows. After rotating keys, take a new full backup.

    For more details, see [Limitations of pg_tde](../index/tde-limitations.md#limitations-when-using-pg_tde).

`pg_tde` has been tested with the following key providers:

| KMS Provider       | Description                                           | Documentation |
|--------------------|-------------------------------------------------------|---------------|
| **KMIP**           | Standard Key Management Interoperability Protocol.    | [Configure KMIP →](kmip-server.md) |
| **Vault**          | HashiCorp Vault integration (KV v2 API). | [Configure Vault →](vault.md) |
| **Fortanix**       | Fortanix DSM key management.                          | [Configure Fortanix →](kmip-fortanix.md) |
| **Thales**         | Thales CipherTrust Manager and DSM.                   | [Configure Thales →](kmip-thales.md) |
| **OpenBao**        | Community fork of Vault, supporting KV v2.            | [Configure OpenBao →](openbao.md) |
| **Akeyless**        | A cloud-based secrets management platform for securely storing and accessing credentials and encryption keys.            | [Configure Akeyless →](kmip-akeyless.md) |
| **Keyring file** *(not recommended)* | Local key file for dev/test only.                  | [Configure keyring file →](keyring.md) |
