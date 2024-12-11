# Install `pg_tde` on Red Hat Enterprise Linux and derivatives

The packages for the tech preview `pg_tde` are available in the experimental repository for Percona Distribution for PostgreSQL 17. 

Check the [list of supported platforms](install.md#__tabbed_1_2).

This tutorial shows how to install `pg_tde` with [Percona Distribution for PostgreSQL](https://docs.percona.com/postgresql/latest/index.html).

## Preconditions

### Install `percona-release`

You need the `percona-release` repository management tool that enables the desired Percona repository for you.

1. Install `percona-release`:

    ```bash
    sudo yum -y install https://repo.percona.com/yum/percona-release-latest.noarch.rpm 
    ```

2. Enable the repository

    ```bash
    sudo percona-release enable-only ppg-{{pgversion17}} 
    ```

## Install `pg_tde`

The `pg_tde` extension is a part of the `percona-postgresql{{pgversion17}} package`. So you only need to install this package.

```bash
sudo yum -y install percona-postgresql17 
```

## Next steps

[Setup](setup.md){.md-button}
