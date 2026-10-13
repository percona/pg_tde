from pathlib import Path

import pytest
import stormweaver.testing as st

from pgtde.rewind import ALL_MODES, run_databases


def _snapshot(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def _local_option_checks(p, s) -> None:
    def rewind(*extra):
        return p.tool(
            "pg_tde_rewind", "--debug", "--source-pgdata", s.datadir, "--target-pgdata", p.datadir, "--no-sync", *extra
        )

    st.command_fails(rewind(), msg="pg_rewind with running target")
    st.command_fails(rewind("--no-ensure-shutdown"), msg="pg_rewind --no-ensure-shutdown with running target")
    p.stop()
    st.command_fails(rewind("--no-ensure-shutdown"), msg="pg_rewind with unexpected running source")
    s.stop()
    before = _snapshot(p.datadir)
    st.command_ok(rewind("--dry-run"), "pg_rewind --dry-run")
    assert _snapshot(p.datadir) == before
    s.start()
    p.start()


@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_rewind_basic(mode, cipher, rewind_driver):
    with rewind_driver(cipher) as rw:
        p = rw.setup_primary()
        has_tablespace = p.pg_major >= 17

        if has_tablespace:
            p.safe_sql("CREATE TABLESPACE space_test LOCATION ''")
            p.safe_sql("""
                CREATE TABLE space_tbl (d text) TABLESPACE space_test;
                INSERT INTO space_tbl VALUES ('in primary, before promotion');
            """)
        p.safe_sql("""
            CREATE TABLE tbl1 (d text);
            INSERT INTO tbl1 VALUES ('in primary');
            CREATE TABLE trunc_tbl (d text);
            INSERT INTO trunc_tbl VALUES ('in primary');
            CREATE TABLE tail_tbl (id integer, d text);
            INSERT INTO tail_tbl VALUES (0, 'in primary');
            CREATE TABLE drop_tbl (d text);
            INSERT INTO drop_tbl VALUES ('in primary');
        """)
        p.safe_sql("CHECKPOINT")

        s = rw.create_standby()

        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary, before promotion')")
        p.safe_sql("INSERT INTO trunc_tbl VALUES ('in primary, before promotion')")
        p.safe_sql(
            "INSERT INTO tail_tbl SELECT g, 'in primary, before promotion: ' || g FROM generate_series(1, 10000) g"
        )
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary, after promotion')")
        s.safe_sql("INSERT INTO tbl1 VALUES ('in standby, after promotion')")
        p.safe_sql("INSERT INTO trunc_tbl SELECT 'in primary, after promotion: ' || g FROM generate_series(1, 10000) g")
        # not TRUNCATE: that makes a new relfilenode
        p.safe_sql("DELETE FROM tail_tbl WHERE id > 10")
        p.safe_sql("VACUUM tail_tbl")
        p.safe_sql("INSERT INTO drop_tbl VALUES ('in primary, after promotion')")
        p.safe_sql("DROP TABLE drop_tbl")
        if has_tablespace:
            p.safe_sql("INSERT INTO space_tbl VALUES ('in primary, after promotion')")
            s.safe_sql("INSERT INTO space_tbl VALUES ('in standby, after promotion')")

        if mode == "local":
            _local_option_checks(p, s)

        rw.run_rewind(mode)

        if has_tablespace:
            assert p.safe_sql("SELECT * FROM space_tbl ORDER BY d") == [
                ["in primary, before promotion"],
                ["in standby, after promotion"],
            ]
        assert p.safe_sql("SELECT * FROM tbl1") == [
            ["in primary"],
            ["in primary, before promotion"],
            ["in standby, after promotion"],
        ]
        assert p.safe_sql("SELECT * FROM trunc_tbl") == [["in primary"], ["in primary, before promotion"]]
        assert p.sql_value("SELECT count(*) FROM tail_tbl") == "10001"
        assert p.safe_sql("SELECT * FROM drop_tbl") == [["in primary"]]
        assert st.check_mode_recursive(p.datadir) == []


# pg_tde_rewind with source and target on the same timeline succeeds.
def test_same_timeline(rewind_driver):
    with rewind_driver() as rw:
        p = rw.setup_primary()
        s = rw.create_standby()

        # run_rewind("local") minus its catchup wait: the source is no primary
        p.stop(mode="immediate")
        with p.db.preserve_config() as conf:
            s.stop()
            st.command_ok(
                p.tool(
                    rw.rewind_bin,
                    "--debug",
                    f"--source-pgdata={s.datadir}",
                    f"--target-pgdata={p.datadir}",
                    "--no-sync",
                    f"--config-file={conf}",
                ),
                "pg_rewind local",
            )
        p.rejoin_as_standby(s)


def test_rewind_cli_options_and_invalid_args(tools, tmp_path):
    tools.help_ok("pg_tde_rewind")
    tools.version_ok("pg_tde_rewind")
    tools.options_ok("pg_tde_rewind")

    primary = tmp_path / "primary"
    standby = tmp_path / "standby"
    primary.mkdir()
    standby.mkdir()
    local = ("--target-pgdata", primary, "--source-pgdata", standby)

    st.command_fails(tools.run("pg_tde_rewind", "--debug", *local, "extra_arg1"), msg="too many arguments")
    st.command_fails(tools.run("pg_tde_rewind", "--target-pgdata", primary), msg="no source specified")
    st.command_fails(
        tools.run("pg_tde_rewind", "--debug", *local, "--source-server", "incorrect_source"),
        msg="both remote and local sources specified",
    )
    st.command_fails(
        tools.run("pg_tde_rewind", "--debug", *local, "--write-recovery-conf"),
        msg="no local source with --write-recovery-conf",
    )


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_rewind_multiple_databases(mode, pg_install_dir, sw_log_dir, node_config, keyring_obj):
    run_databases(pg_install_dir, mode, keyring_obj, config=node_config)
