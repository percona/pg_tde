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

5. Test your changes locally. See the [Running tests](#run-tests) section for more information.

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
* CMake
* pkg-config
* gcc or clang
* Percona Server for PostgreSQL 17 or later with development files
* OpenSSL, libcurl, zlib, LZ4 and Zstandard development files

Refer to the [Run manually](#run-manually) section for guidelines.

### Run tests

You can find the tests in the `sql` and `t` directories.

#### Run manually

1. Change the directory to `pg_tde`

2. Build and install `pg_tde` with the following commands:

    ```sh
    meson setup -Dpg_config=/path/to/postgresql/bin/pg_config ./build
    cd build
    meson install
    ```

3. Run the tests using the following command:

    ```sh
    meson install && meson test --print-errorlogs --timeout-multiplier=0
    ```

#### Run automatically

The tests are run automatically with GitHub actions once you create a pull request.

### pytest suite

New tests are written in Python, under `tests/`, on top of [stormweaver](https://github.com/Percona-Lab/stormweaver).
The perl TAP tests in `t/` and the sql tests in `sql/` are moved there one by one.

Run them through meson (`meson setup -Dstormweaver=/path/to/stormweaver`, then `meson test --suite pytest`) or directly:

    stormweaver test tests --pg-config /path/to/pg_config
    stormweaver test tests --pg-config /path/to/pg_config --all-values    # every available keyring
    stormweaver test tests --pg-config /path/to/pg_config --matrix keyring=vault,kmip

Conventions:

* One test function per intent, the intent is the function name or a one line comment above it.
* The statement a test is about is written as plain SQL in the test body. Helpers are for setup (`tests/conftest.py` fixtures) and for oracles (`tests/pgtde/checks.py`).
* `node.tde` (`tests/pgtde/tde.py`) has the pg_tde SQL functions, `node.execute/query/row/scalar` run SQL. Results are typed and can be compared to tuples or dicts.
* Use the `keyring` fixture for key providers, the test then runs on every keyring kind with `--all-values`.

## Documentation contribution

To contribute to the documentation, see the following [Documentation contribution guide](/documentation/documentation-contributing.md).

## After your pull request is merged

Once your pull request is merged, you are an official Percona Community Contributor. Welcome to the community!
