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

1. From a build directory. Build and install `pg_tde`, then run the fast suite (the default) or the matrix run:

    ```sh
    meson setup build -Dpg_config=/path/to/postgresql/bin/pg_config [-Dstormweaver=/path/to/stormweaver]
    meson install -C build
    meson test -C build --print-errorlogs
    meson test -C build --suite all-values --print-errorlogs
    ```

    See [Meson suites](#meson-suites) for the other suites.

2. Against any installed setup, from a checkout:

    ```sh
    stormweaver test tests --pg-config /path/to/postgresql/bin/pg_config
    ```

    Use `-k <expr>` to select tests.
    The matrix options are described in [Matrix options](#matrix-options).
    `stormweaver test` passes all other arguments through to pytest.

3. Tests only, without building anything. This registers the test suite and skips all build targets, so it can run against an existing installation:

    ```sh
    meson setup build-tests -Dtests_only=true -Dpg_config=/path/to/postgresql/bin/pg_config
    meson test -C build-tests
    ```

#### Test layout

```
tests/
  conftest.py          cross-topic options, fixtures, dimensions
  pgtde/               helper package and its unit tests
  extension/
  encryption/
  keys/
  keyrings/
  wal/
  recovery/
  backup/
  replication/
  rewind/
  upgrade/
  tools/
  stress/              randomized stress scenarios
  fixtures/
```

Each topic directory has an empty `__init__.py`, so module basenames like `test_basic.py` can repeat across topics.
Topic-specific fixtures go into `<topic>/conftest.py`.

A test goes where the behavior it exercises lives, not where the binary it runs lives.
`pg_tde_waldump` tests are in `wal/`.
`pg_tde_rewind` has its own `rewind/` directory because it is a large feature.
`tools/` is only for frontend tools without another home.
`keyrings/` is for behavior specific to one backend (vault mounts and namespaces, kmip certificates, server revalidation).
Keyring-agnostic behavior is tested in its own topic and runs on all keyrings through the `keyring` dimension.

New modules must be added to the `pytest_files` list in `meson.build`.

#### Module conventions

* A module covers one feature, a test function is one scenario.
  Use plain functions, no test classes.
* Variants are `pytest.mark.parametrize`, never copies.
  Scenarios sharing setup share a fixture or a module-level scenario helper.
* Test names describe the scenario (`test_rotate_principal_key_keeps_data_readable`, not `test_rotate_key`).
* Bug regressions carry `@pytest.mark.bug("PG-xxxx")` and live in the module of their topic.
  There is no `bugs/` directory.
* Topic-only fixtures go into `<topic>/conftest.py`, the root `conftest.py` only keeps cross-topic ones.
* Run binaries through `node.tool(name, ...)` when a node is involved and through the `tools` fixture otherwise, never through `run_bin` directly.
  Exceptions need a comment (e.g. stderr redirected to a file, `rewind/test_files.py`).
* Tests that do not care about the keyring use `keyring_obj` (or a setup fixture built on it).
  Tests that depend on file provider internals (moving or corrupting the key file, file paths in CLI arguments) use `file_keyring`.
* Archive and restore commands come from `pgtde.wal`.
  Checks shared between modules live in `pgtde/` (e.g. `pgtde/checks.py`).
  Test modules never import other test modules.

#### Fixtures

Root `tests/conftest.py`:

| Fixture | Gives | Dimensions |
|---|---|---|
| `tde_node` | fresh started node, `pg_tde` preloaded, extension not created | io_method |
| `keyring_obj` | provider-ready keyring from the `keyring` dimension | keyring |
| `tde_node_db` | `tde_node` + extension, database provider and key from `keyring_obj` | io_method, keyring |
| `tde_node_global` | `tde_node` + global provider, server key, `wal_encrypt=on`, restarted | io_method, keyring |
| `tde_node_default` | `tde_node` + global provider, default key | io_method, keyring |
| `file_keyring` | explicit file keyring | none |
| `tde_node_factory` | `factory(name, config={...}, start=True, install=None, initdb_args=None, extra_initdb_args=None, preload=...) -> TdeNode` for multi-node tests and nodes on another install, same io_method wiring per node | io_method |
| `upgrade` | one `--old-pg-config` entry per test run, see [Old installs](#old-installs) | old installs |
| `node_config` | server settings every node gets: `io_method`, and `pg_tde.cipher` if the test requests `cipher` | io_method |
| `tools` | nodeless binary runner with `help_ok`, `version_ok`, `options_ok` | none |

`tests/rewind/conftest.py` adds `rewind_driver`, a factory for `TdeRewindDriver` that takes the keyring and `node_config` from the fixtures.

Every test that gets a node through `tde_node` or `tde_node_factory` is on the `io_method` dimension.
`cipher` is opt-in, request it in tests where the cipher matters.

Extra server settings for a single test go through `@pytest.mark.node_config({...})`.
They are merged into the `node_config` fixture, so `tde_node`, the setup fixtures built on it and every node made by the factory get them.
The marker closest to the test wins.
`node_config(initdb_args=[...])` adds `initdb` arguments, a factory call can override them with `initdb_args=`, or add to them with `extra_initdb_args=`.
With `install=` the factory drops `io_method` for installs older than 18.

For multi-node tests the factory does not create providers.
Set the keys up on the primary from `keyring_obj`, standbys and backups inherit them.

#### Matrix options

The dimensions `keyring`, `io_method` and `cipher` are registered in `tests/conftest.py`.
A test is on a dimension when it requests it, directly or through a fixture.
By default each dimension has a single value, so a normal run is not multiplied.
The examples assume `PGC=/path/to/postgresql/bin/pg_config`.

* `--all-values`: every value of every requested dimension runs at least once.
  One dimension varies at a time, the others stay at their default, so the cost is additive.
  For a test using all three dimensions on PG18 that is 1 + 2 + 3 + 1 = 7 runs, with all keyrings available.

    ```sh
    stormweaver test tests/keys --pg-config $PGC --all-values
    ```

* `--all-combinations`: the cartesian product of all values of all requested dimensions.
  The cost multiplies, use it for manual runs only.

    ```sh
    stormweaver test tests/rewind/test_encrypted.py --pg-config $PGC --all-combinations
    ```

* `--matrix name=v1,v2`: explicit values for one dimension, cartesian across the dimensions named.
  Dimensions not named follow `--all-values` or `--all-combinations` if given, otherwise their default.

    ```sh
    stormweaver test tests/encryption --pg-config $PGC --matrix cipher=aes_128,aes_256
    ```

* `STORMWEAVER_KEYRINGS`: only matters when keyring values are expanded (`--all-values`, `--all-combinations`, `--matrix keyring=...`).
  It restricts the keyring values to the listed kinds, and a listed kind that is not available is an error.

    ```sh
    STORMWEAVER_KEYRINGS=file,kmip stormweaver test tests/keys --pg-config $PGC --all-values
    ```

The options `--keyrings`, `--io-methods` and `--ciphers` (or the environment variables `PG_TDE_TEST_KEYRINGS`, `PG_TDE_TEST_IO_METHODS` and `PG_TDE_TEST_CIPHERS`) override the available values of one dimension.
`--keyrings` takes precedence over `STORMWEAVER_KEYRINGS`.

`--all-values` and `--all-combinations` cannot be used together.
Test ids are `name-value`, so `-k keyring-kmip` selects one value.

#### Meson suites

Every test module is registered as `<topic>/<module>` (without the `test_` prefix), for example `rewind/encrypted`.

| Suite | Contains |
|---|---|
| `fast` | every module, run with default dimension values. This is what plain `meson test` runs |
| `<topic>` | the modules of one topic, e.g. `rewind` |
| `all-values` | the `<topic>/<module>/all-values` twins, run with `--all-values` |
| `<topic>-all-values` | the twins of one topic, e.g. `rewind-all-values` |
| `old-install` | `upgrade/old-install`, the `old_install` tests against `-Dold_pg_configs`. Only registered when the option is set, not part of plain `meson test` |

```sh
meson test -C build                          # fast suite
meson test -C build --suite rewind           # one topic
meson test -C build --suite all-values       # matrix run of everything
meson test -C build --suite rewind-all-values
```

`--all-combinations` is not registered in meson, run it by hand with `stormweaver test`.

#### Keyring services

The vault and KMIP tests need an OpenBao (`bao`) and a Cosmian KMS (`cosmian_kms`) server. Stormweaver starts them automatically when the binary is on `PATH`, or when a container runtime is available. You can configure them in the `[keyring.vault]` and `[keyring.kmip]` sections of stormweaver's `stormweaver.toml`.

In a plain run, tests marked `needs_vault` or `needs_kmip` skip when the service binary or container is not available.
This does not depend on `STORMWEAVER_KEYRINGS`, which only affects tests on the `keyring` dimension.
To make a missing service an error for the dimension tests, set `STORMWEAVER_KEYRINGS=vault,kmip` and pass `--all-values`.
Tests in `keyrings/` skip without the service.

#### Old installs

Upgrade tests need an older installation next to the one under test.
`--old-pg-config` (or `PG_TDE_TEST_OLD_PG_CONFIG` when the option is not given) takes a comma separated list, and it can be repeated.
Every test using the `upgrade` fixture runs once per entry.
Without entries these tests are collected once and skip with "set --old-pg-config".

There are 2 kinds of entries.

* A `pg_config` path (dir mode): the old installation is on disk next to the new one, in a different prefix.
  Any major works, so this is how cross-major upgrades are tested.

    ```sh
    stormweaver test tests --pg-config $PGC --old-pg-config /usr/lib/postgresql/17/bin/pg_config,/opt/pg18-tde21/bin/pg_config
    stormweaver test tests -m old_install --pg-config $PGC --old-pg-config /usr/lib/postgresql/16/bin/pg_config
    ```

* `script:<cmd>` (script mode): for package installs, where the old and new version can't be on disk at the same time.
  The suite runs `<cmd> old` and `<cmd> new`, the command must exit with 0, and after it returns the installation behind `--pg-config` must be the requested version.
  Arguments in `<cmd>` are passed before `old`/`new`, `tests/upgrade/switch.sh.example` shows the idea.

    ```sh
    stormweaver test tests -m old_install --pg-config $PGC --old-pg-config "script:ci/switch-pg-tde.sh 2.1.2"
    ```

  A script entry must be its own `--old-pg-config` value, because a command line can contain commas.
  `script:` after a comma is a usage error.
  The script switches the same prefix, so the old version must have the same major.

  Script mode changes the installation every other test uses, which has some consequences:
  with a `script:` entry only `old_install` tests run, everything else is deselected, and xdist (`-n`) is a usage error.
  At startup the suite runs `<cmd> new` first, so an install left on old by an aborted run is fine, then `old` and `new` again to probe the old version.
  The `upgrade` fixture switches back to new at teardown, and so does the end of the session.

Each entry gets a label `pg<major>-tde<default_version>` from its `pg_config` and `pg_tde.control`, for example `pg17-tde2.2`.
Duplicates get `-2`, `-3`, ...
The label is the first part of the test id, so `-k pg17-tde2.2` selects that entry.
`-k` is a substring match though, it also catches the duplicates (`pg17-tde2.2-2`), use the full test id when you need exactly one.
The run header lists the entries and their mode.

Tests using `upgrade` get the `old_install` marker automatically, so `-m old_install` selects all of them.
The marker also takes gates, a test skips for an entry that doesn't match with "`<label>`: needs `<gate>`=`<value>`":

* `same_major`: the old install has the same major as `--pg-config`
* `tde_differs`: the old `pg_tde` default version is not the one under test, use it for release to release behavior
* `side_by_side`: dir mode, both installs on disk at the same time

From meson, set the list once and run the `old-install` suite:

```sh
meson configure build -Dold_pg_configs=/usr/lib/postgresql/17/bin/pg_config && meson test -C build --suite old-install
```

##### Writing an old-install test

`upgrade` must be the first argument of the test.
Fixture teardown runs in reverse setup order, so this way it switches back to new only after the factory stopped the nodes.
`upgrade.old_node(tde_node_factory, name)` makes a started node on the old install.
For `pg_upgrade`, `upgrade.new_node(tde_node_factory, name, old)` makes the unstarted target (with the checksum setting of the old cluster), and `upgrade.run_pg_tde_upgrade(old, new, socketdir=..., cwd=...)` runs it.
This needs both installs on disk, so mark the test `@pytest.mark.old_install(side_by_side=True)`.
`upgrade.start_in_place(node)` restarts the old node on the new binaries and runs `ALTER EXTENSION pg_tde UPDATE` everywhere, mark it `same_major=True`.
`upgrade.old_tde` and `upgrade.suite_tde` are the 2 `pg_tde` versions.
See `upgrade/test_pg_upgrade.py` for examples.

#### Logs

Each run writes `logs/<run>/main.log` in the working directory, next to the server logs of every node. With `meson test`, use `--print-errorlogs` to print the output of failed tests.

#### Run automatically

The tests are run automatically with GitHub actions once you create a pull request.

## Documentation contribution

To contribute to the documentation, see the following [Documentation contribution guide](/documentation/documentation-contributing.md).

## After your pull request is merged

Once your pull request is merged, you are an official Percona Community Contributor. Welcome to the community!
