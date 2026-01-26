# Install pg_tde on Debian or Ubuntu

This page explains how to install `pg_tde` for [Percona Distribution for PostgreSQL :octicons-link-external-16:](https://docs.percona.com/postgresql/latest/index.html).

!!! tip
    Check the [list of supported platforms :octicons-link-external-16:](https://www.percona.com/services/policies/percona-software-support-lifecycle) before continuing.

## Preconditions {.power-number}

1. Remove any upstream PostgreSQL packages (postgresql-*) that may already be installed on Debian or other apt-based systems. These packages conflict with Percona Server for PostgreSQL and with the standalone `pg_tde` package.
2. Ensure you enable the Percona APT repository using the repository management tool `percona-release`. This ensures the correct Percona Server for PostgreSQL and pg_tde packages are available for installation.

## Install percona-release {.power-number}

1. You need the following dependencies to install `percona-release`:

    - `wget`
    - `gnupg2`
    - `curl`
    - `lsb-release`

    Install the dependencies:

    ```{.bash data-prompt="$"}
    sudo apt-get install -y wget gnupg2 curl lsb-release
    ```

2. Fetch the `percona-release` package

    ```{.bash data-prompt="$"}
    sudo wget https://repo.percona.com/apt/percona-release_latest.generic_all.deb
    ```

3. Install `percona-release`

    ```{.bash data-prompt="$"}
    sudo dpkg -i percona-release_latest.generic_all.deb
    ```

4. Enable the Percona Distribution for PostgreSQL repository

    ```{.bash data-prompt="$"}
    sudo percona-release enable-only ppg-{{pgversion17}}
    ```

5. Update the local cache

    ```{.bash data-prompt="$"}
    sudo apt-get update
    ```

## Install pg_tde {.power-number}  

After all [preconditions](#preconditions) are met, install the `pg_tde` package:

```{.bash data-prompt="$"}
sudo apt-get install -y percona-pg-tde(pg-version)
```

### Example for PostgreSQL 17

```{.bash data-prompt="$"}
sudo apt-get install -y percona-pg-tde17
```

## Next steps

[Configure pg_tde :material-arrow-right:](setup.md){.md-button}
