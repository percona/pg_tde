# Code contributing guide

Welcome to `pg_tde` - the Transparent Database Encryption for PostgreSQL!

We're glad that you would like to become a Percona community member and participate in keeping open source open.

You can contribute in one of the following ways:

1. Reach us on our [Forums](https://forums.percona.com/c/postgresql/pg-tde-transparent-data-encryption-tde/82).
2. [Submit a bug report or a feature request](#submit-a-bug-report-or-a-feature-request)
3. [Submit a pull request (PR) with the code patch](#submit-a-pull-request)
4. [Contribute to documentation](#documentation-contribution)

By contributing, you agree to the [Percona Community code of conduct](https://github.com/percona/community/blob/main/content/contribute/coc.md).

## Submit a bug report or a feature request

All bug reports, enhancements and feature requests are tracked in [Jira issue tracker](https://jira.percona.com/projects/PG). If you would like to suggest a new feature / an improvement or you found a bug in `pg_tde`, please submit the report to the [PG project](https://jira.percona.com/projects/PG/issues).

Start by searching the open tickets for a similar report. If you find that someone else has already reported your issue, then you can upvote that report to increase its visibility.

If there is no existing report, submit your report following these steps:

1. Sign in to [Jira issue tracker](https://jira.percona.com/projects/PG/issues). You will need to create an account if you do not have one.
2. In the _Summary_, _Description_, _Steps To Reproduce_, _Affects Version_ fields describe the problem you have detected or an idea that you have for a new feature or improvement.
3. As a general rule of thumb, try to create bug reports that are:

  * Reproducible: describe the steps to reproduce the problem.
  * Unique: check if there already exists a JIRA ticket to describe the problem.
  * Scoped to a Single Bug: only report one bug in one JIRA ticket

## Submit a pull request

Though not mandatory, we encourage you to first check for a bug report among Jira issues and in the PR list: perhaps the bug has already been addressed.

For feature requests and enhancements, we do ask you to create a Jira issue, describe your idea and discuss the design with us. This way we align your ideas with our vision for the product development.

If the bug hasn’t been reported / addressed, or we’ve agreed on the enhancement implementation with you, do the following:

1. [Fork](https://docs.github.com/en/github/getting-started-with-github/fork-a-repo) this repository

2. Clone this repository on your machine

3. Create a separate branch for your changes. If you work on a Jira issue, please include the issue number in the branch name so it reads as `<JIRAISSUE>-my_branch`.

4. Make your changes. Follow the guidelines outlined in the [PostgreSQL Coding Standard](https://www.postgresql.org/docs/current/source.html) to improve code readability.

5. Test your changes locally. See the [Running tests](#running-tests) section for more information.

6. To update the documentation describing your changes, see [Documentation contribution](#documentation-contribution).

7. Commit the changes. Add the Jira issue number at the beginning of your message subject, so that is reads as `<JIRAISSUE> : My commit message`.  Follow this pattern for your commits:

    ```
    PG-1234:  Main commit message.
    <Blank line>
    Details of fix.
    ```

    See the [commit message guidelines](https://gist.github.com/robertpainsi/b632364184e70900af4ab688decf6f53) for more information.

8. Open a pull request to Percona
9. Our team will review your code and if everything is correct, will merge it. Otherwise, we will contact you for additional information or with the request to make changes.

### Build pg_tde

To build `pg_tde` from source code, you require the following:

* git
* Meson
* gcc or clang
* Percona Server for PostgreSQL 17 or later

Refer to the [Building from source code](https://github.com/percona/pg_tde?tab=readme-ov-file#building-from-sources-for-community-postgresql) section for guidelines.

### Run tests

The tests live in `tests/` and run with pytest through stormweaver. `tests/stress/` holds randomized stress scenarios, which you run with `stormweaver <file>`.

#### Prerequisites

* A PostgreSQL installation with `pg_tde` installed (`meson install`).
* The `stormweaver` package. It ships its own Python 3.14. Install it from the OBS packages, or from a source checkout of [stormweaver](https://github.com/Percona-Lab/stormweaver).
* `psql`, from the PostgreSQL client package.

#### Run manually

There are three ways to run the suite.

1. From a build directory. Build and install `pg_tde`, then run the fast suite (the default) or the full one:

    ```sh
    meson setup build -Dpg_config=/path/to/postgresql/bin/pg_config [-Dstormweaver=/path/to/stormweaver]
    meson install -C build
    meson test -C build --print-errorlogs
    meson test -C build --suite full --print-errorlogs
    ```

2. Against any installed setup, from a checkout:

    ```sh
    stormweaver test tests --pg-config /path/to/postgresql/bin/pg_config
    ```

    Useful options are `-k <expr>` to select tests and `--full` to run every matrix dimension at every available value (`--matrix cipher=aes_128,aes_256` picks values for one dimension). The dimensions `keyring`, `io_method` and `cipher` are registered in `tests/conftest.py`; the ported tests still fix their own values, so the matrix only grows the run once tests start requesting these fixtures. `stormweaver test` passes all other arguments through to pytest.

3. Tests only, without building anything. This registers the test suite and skips all build targets, so it can run against an existing installation:

    ```sh
    meson setup build-tests -Dtests_only=true -Dpg_config=/path/to/postgresql/bin/pg_config
    meson test -C build-tests
    ```

#### Keyring services

The vault and KMIP tests need an OpenBao (`bao`) and a Cosmian KMS (`cosmian_kms`) server. Stormweaver starts them automatically when the binary is on `PATH`, or when a container runtime is available. You can configure them in the `[keyring.vault]` and `[keyring.kmip]` sections of stormweaver's `stormweaver.toml`.

Tests that need a service skip when it is not available. Set `STORMWEAVER_KEYRINGS=vault,kmip` to make a missing service an error instead.

#### Logs

Each run writes `logs/<run>/main.log` in the working directory, next to the server logs of every node. With `meson test`, use `--print-errorlogs` to print the output of failed tests.

#### Run automatically

The tests are run automatically with GitHub actions once you create a pull request.

## Documentation contribution

To contribute to the documentation, see the following [Documentation contribution guide](/documentation/documentation-contributing.md).

## After your pull request is merged

Once your pull request is merged, you are an official Percona Community Contributor. Welcome to the community!
