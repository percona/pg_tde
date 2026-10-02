# Versions and Supported PostgreSQL deployments

The `pg_tde` extension is available for Percona Server for PostgreSQL [17.5](https://docs.percona.com/postgresql/17/) and later versions, an open source, drop-in replacement for PostgreSQL Community. These versions provide the tde_heap access method and offer full encryption capabilities, including encryption of tables, indexes and WAL data.

For users who need PostgreSQL 16, a pg_tde build is available as a [Tech Preview](https://docs.percona.com/postgresql/16/percona-ext.html#tech-preview-pg_tde-built-into-percona-server-for-postgresql-16). It is not officially supported, is not recommended for production, and does not follow the same release cadence as the supported PostgreSQL [17.5](https://docs.percona.com/postgresql/17/) and later versions.

The extension is tightly integrated with Percona Server for PostgreSQL to deliver enhanced encryption functionality that is not available in community builds.

## Why choose Percona Server for PostgreSQL?

By using our PostgreSQL distribution, you get:

- **Full encryption support** through the `tde_heap` access method, including tables, indexes and WAL data.
- **Enhanced performance and enterprise-ready features** not available in community builds.
- **Regular updates and security patches** backed by Percona’s expert support team.
- **Professional support** and guidance for secure PostgreSQL deployments.

!!! note
    Support for earlier or limited versions of `pg_tde` (such as `tde_heap_basic`) has been deprecated.

Still unsure which deployment fits your needs? [Contact our experts](https://www.percona.com/about/contact) to find the best solution for your environment.

[Get started with installation :material-arrow-right:](../install.md){.md-button}
