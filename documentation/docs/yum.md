# Install pg_tde on Red Hat Enterprise Linux and Derivatives

This tutorial shows how to install `pg_tde` with [Percona Distribution for PostgreSQL](https://docs.percona.com/postgresql/latest/index.html).

!!! tip
    Check the [list of supported platforms :octicons-link-external-16:](https://www.percona.com/services/policies/percona-software-support-lifecycle) before continuing.

## Install percona-release {.power-number}

You need the `percona-release` repository management tool that enables the desired Percona repository for you.

1. Install `percona-release`:

    ```{.bash data-prompt="$"}
    sudo yum -y install https://repo.percona.com/yum/percona-release-latest.noarch.rpm
    ```

2. Enable the repository:

    ```{.bash data-prompt="$"}
    sudo percona-release enable-only ppg-{{pgversion17}}
    ```

## Install pg_tde {.power-number}

Install `pg_tde`:

```{.bash data-prompt="$"}
sudo yum install -y percona-pg_tde(pg-version)
```

### Example for PostgreSQL 18

```{.bash data-prompt="$"}
sudo yum install -y percona-pg_tde18
```

## Next steps

[Configure pg_tde :material-arrow-right:](setup.md){.md-button}
