# Install `pg_tde` on Debian or Ubuntu

The packages for the tech preview `pg_tde` are available in the experimental repository for Percona Distribution for PostgreSQL 17. 

Check the [list of supported platforms](install.md#__tabbed_1_2).

This tutorial shows how to install `pg_tde` with [Percona Distribution for PostgreSQL](https://docs.percona.com/postgresql/latest/index.html).

## Preconditions

1. Debian and other systems that use the `apt` package manager include the upstream PostgreSQL server package (`postgresql-{{pgversion17}}`) by default. You need to uninstall this package before you install Percona Server for PostgreSQL and `pg_tde` to avoid conflicts.
2. You need the `percona-release` repository management tool that enables the desired Percona repository for you.

## Install `percona-release`

1. You need the following dependencies to install `percona-release`:
    
    - `wget`
    - `gnupg2`
    - `curl`
    - `lsb-release`
    
    Install them with the following command:
    
    ```bash
    sudo apt-get install -y wget gnupg2 curl lsb-release
    ```
    
2. Fetch the `percona-release` package

    ```bash
    sudo wget https://repo.percona.com/apt/percona-release_latest.generic_all.deb
    ```

3. Install `percona-release`

    ```bash
    sudo dpkg -i percona-release_latest.generic_all.deb
    ```

4. Enable the Percona Distribution for PostgreSQL repository

    Percona provides [two repositories](repo-overview.md) for Percona Distribution for PostgreSQL. We recommend enabling the Major release repository to timely receive the latest updates. Since the extension is in the {{release}} stage, enable the testing repository.

    ```{.bash data-prompt="$"}
    $ sudo percona-release enable ppg-{{pgversion17}} testing
    ```

6. Update the local cache

    ```bash
    sudo apt-get update
    ```

## Install `pg_tde`

The `pg_tde` extension is a part of the `percona-postgresql-{{pgversion17}} package`. So you only need to install this package.

After all [preconditions](#preconditions) are met, run the following command:


```bash
sudo apt-get install -y percona-postgresql-17 
```


## Next step 

[Setup](setup.md){.md-button}
