# Install pg_tde

You can select from multiple easy-to-follow installation options to install `pg_tde`, however **we strongly recommend using a Package Manager** for a convenient and quick installation.

<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< HEAD
!!! note
    Specific information on the supported platforms, products, and versions is described in the [Percona Software and Platform Lifecycle :octicons-link-external-16:](https://www.percona.com/services/policies/percona-software-support-lifecycle) page.
|||||||||||||||||||||||||||||||| 2f0315d
To install `pg_tde`, use one of the following methods:
================================
`pg_tde` availability by PostgreSQL version:

| **PostgreSQL Version** | **Is pg_tde installed automatically?** | **Action Required** |
| -------- | -------- | -------- |
| 17.x (minor updates) | Yes | None |
| 18.x (or later)  | No | Install package manually |

!!! note
    Specific information on the supported platforms, products, and versions is described in the [Percona Software and Platform Lifecycle :octicons-link-external-16:](https://www.percona.com/services/policies/percona-software-support-lifecycle) page.
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> release-2.1

=== ":octicons-terminal-16: Package manager"

    Percona provides installation packages in DEB and RPM formats for 64-bit Linux distributions.

    If you are on Debian or Ubuntu, use `apt` for installation.

    If you are on Red Hat Enterprise Linux or compatible derivatives, use `yum` for installation.

    [Install on Debian or Ubuntu :material-arrow-right:](apt.md){.md-button}
    [Install on RHEL or derivatives :material-arrow-right:](yum.md){.md-button}

=== ":simple-docker: Docker"

    `pg_tde` is a part of the Percona Distribution for PostgreSQL Docker image. Use this image to enjoy full encryption capabilities. Check below to get access to a detailed step-by-step guide. 

    [Run in Docker :octicons-link-external-16:](https://docs.percona.com/postgresql/17/docker.html#enable-encryption){.md-button}

<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< HEAD
=== ":simple-kubernetes: Kubernetes"

    You can enable `pg_tde` when deploying Percona Server for PostgreSQL in Kubernetes using the Percona Operator.

=== ":octicons-download-16: Tar download (not recommended)"
|||||||||||||||||||||||||||||||| 2f0315d
=== ":octicons-download-16: Tar download"
================================
=== ":octicons-download-16: Tar download (not recommended)"
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> release-2.1

    `pg_tde` is included in the Percona Distribution for PostgreSQL tarball. Select the below link to access the step-by-step guide. 

    [Install from tarballs :material-arrow-right:](https://docs.percona.com/postgresql/{{pgversion}}/tarball.html){.md-button}

## Next steps

<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< HEAD
After finishing the installation, proceed with:
|||||||||||||||||||||||||||||||| 2f0315d
[Configure pg_tde :material-arrow-right:](setup.md){.md-button}
================================
After finishing the installation, you can proceed with:
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> release-2.1

<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< HEAD
- [Set up `pg_tde`](setup.md)
- [Learn about key management](global-key-provider-configuration/overview.md)
- [Validate your encryption setup](test.md)
- [Enable WAL encryption](wal-encryption.md)
|||||||||||||||||||||||||||||||| 2f0315d
If you’ve already completed these steps, feel free to skip ahead to a later section:

 [Configure Key Management (KMS)](global-key-provider-configuration/overview.md){.md-button} [Validate Encryption with pg_tde](test.md){.md-button} [Configure WAL encryption](wal-encryption.md){.md-button}
================================
[Set up pg_tde](setup.md){.md-button}
[Learn about key management](global-key-provider-configuration/overview.md){.md-button}
[Validate your encryption setup](test.md){.md-button}
[Enable WAL encryption](wal-encryption.md){.md-button}
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> release-2.1
