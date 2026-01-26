# Install pg_tde

You can select from multiple easy-to-follow installation options to install `pg_tde`, however **we strongly recommend using a Package Manager** for a convenient and quick installation.

`pg_tde` availability by PostgreSQL version:

| **PostgreSQL version** | **Is pg_tde installed automatically?** | **Action Required** |
| -------- | -------- | -------- |
| 17.x - 17.6 (minor updates) | Yes | None |
| 17.7 (and later) | No | Install percona-pg-tde-(pg-version) package manually |
| 18.x (and later)  | No | Install percona-pg-tde-(pg-version) package manually |

!!! important
    Starting with PPG 17.7, `pg_tde` is no longer bundled with the Percona server for PostgreSQL package. It is now delivered as a separate package named `percona-pg-tde-(pg-version)`.

!!! note
    Specific information on the supported platforms, products, and versions is described in the [Percona Software and Platform Lifecycle :octicons-link-external-16:](https://www.percona.com/services/policies/percona-software-support-lifecycle) page.

=== ":octicons-terminal-16: Package manager"

    Percona provides installation packages in DEB and RPM formats for 64-bit Linux distributions.

    If you are on Debian or Ubuntu, use `apt` for installation.

    If you are on Red Hat Enterprise Linux or compatible derivatives, use `yum` for installation.

    [Install on Debian or Ubuntu :material-arrow-right:](apt.md){.md-button}
    [Install on RHEL or derivatives :material-arrow-right:](yum.md){.md-button}

=== ":simple-docker: Docker"

    `pg_tde` is a part of the Percona Distribution for PostgreSQL Docker image. Use this image to enjoy full encryption capabilities. Check below to get access to a detailed step-by-step guide. 

    [Run in Docker :octicons-link-external-16:](https://docs.percona.com/postgresql/17/docker.html#enable-encryption){.md-button}

=== ":simple-kubernetes: Kubernetes"

    You can enable `pg_tde` when deploying Percona Server for PostgreSQL in Kubernetes using the Percona Operator.

=== ":octicons-download-16: Tar download (not recommended)"

    `pg_tde` is included in the Percona Distribution for PostgreSQL tarball. Select the below link to access the step-by-step guide. 

    [Install from tarballs :material-arrow-right:](https://docs.percona.com/postgresql/{{pgversion}}/tarball.html){.md-button}

## Next steps

After finishing the installation, you can proceed with:

[Set up pg_tde](setup.md){.md-button}
[Learn about key management](global-key-provider-configuration/overview.md){.md-button}
[Validate your encryption setup](test.md){.md-button}
[Enable WAL encryption](wal-encryption.md){.md-button}
