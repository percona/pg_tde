import re
import tempfile

import pytest
import stormweaver.testing as st

from pgtde.node import TdeNode

WORKLOAD = [
    # heap, btree, hash, sequence
    "CREATE TABLE t1 (a int GENERATED ALWAYS AS IDENTITY, b text)",
    "CREATE INDEX i1a ON t1 USING btree (a)",
    "CREATE INDEX i1b ON t1 USING hash (b)",
    "INSERT INTO t1 VALUES (default, 'one'), (default, 'two')",
    "DELETE FROM t1 WHERE b = 'one'",
    "TRUNCATE t1",
    # abort
    "START TRANSACTION; INSERT INTO t1 VALUES (default, 'three'); ROLLBACK",
    # unlogged/init fork
    "CREATE UNLOGGED TABLE t2 (x int)",
    "CREATE INDEX i2 ON t2 USING btree (x)",
    "INSERT INTO t2 SELECT generate_series(1, 10)",
    # gin
    "CREATE TABLE gin_idx_tbl (id bigserial PRIMARY KEY, data jsonb)",
    "CREATE INDEX gin_idx ON gin_idx_tbl USING gin (data)",
    """INSERT INTO gin_idx_tbl
    WITH random_json AS (
        SELECT json_object_agg(key, trunc(random() * 10)) as json_data
            FROM unnest(array['a', 'b', 'c']) as u(key))
          SELECT generate_series(1,500), json_data FROM random_json""",
    # gist, spgist
    "CREATE TABLE gist_idx_tbl (p point)",
    "CREATE INDEX gist_idx ON gist_idx_tbl USING gist (p)",
    "CREATE INDEX spgist_idx ON gist_idx_tbl USING spgist (p)",
    "INSERT INTO gist_idx_tbl (p) VALUES (point '(1, 1)'), (point '(3, 2)'), (point '(6, 3)')",
    # brin
    "CREATE TABLE brin_idx_tbl (col1 int, col2 text, col3 text )",
    "CREATE INDEX brin_idx ON brin_idx_tbl USING brin (col1, col2, col3) WITH (autosummarize=on)",
    "INSERT INTO brin_idx_tbl SELECT generate_series(1, 10000), 'dummy', 'dummy'",
    "UPDATE brin_idx_tbl SET col2 = 'updated' WHERE col1 BETWEEN 1 AND 5000",
    "SELECT brin_summarize_range('brin_idx', 0)",
    "SELECT brin_desummarize_range('brin_idx', 0)",
    "VACUUM",
    # logical message
    "SELECT pg_logical_emit_message(true, 'foo', 'bar')",
    # relmap
    "VACUUM FULL pg_authid",
    # database
    "CREATE DATABASE d1",
    "DROP DATABASE d1",
]

LSN_SQL = "SELECT pg_current_wal_insert_lsn(), pg_walfile_name(pg_current_wal_insert_lsn())"


@pytest.fixture
def tblspc_dir():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        yield d


def test_pg_waldump_basic(pg_install_dir, sw_log_dir, pg_major, tmp_path, tblspc_dir):
    config = {
        "autovacuum": "off",
        "checkpoint_timeout": "1h",
        # for standbydesc
        "archive_mode": "on",
        "archive_command": "",
        # for XLOG_HEAP_TRUNCATE
        "wal_level": "logical",
    }
    with TdeNode.fresh(pg_install_dir, name="main", config=config) as node:
        node.setup_server_key(tmp_path / "global.keys", provider="file-keyring-wal", key="server-key")
        node.db.add_config({"pg_tde.wal_encrypt": "on"})
        node.restart()

        [[start_lsn, start_walfile]] = node.safe_sql(LSN_SQL)

        for sql in WORKLOAD:
            node.safe_sql(sql)
        node.safe_sql(f"CREATE TABLESPACE ts1 LOCATION '{tblspc_dir}'")
        node.safe_sql("DROP TABLESPACE ts1")

        [[end_lsn, end_walfile]] = node.safe_sql(LSN_SQL)

        default_ts_oid = node.sql_value("SELECT oid FROM pg_tablespace WHERE spcname = 'pg_default'")
        postgres_db_oid = node.sql_value("SELECT oid FROM pg_database WHERE datname = 'postgres'")
        rel_t1_oid = node.sql_value("SELECT oid FROM pg_class WHERE relname = 't1'")
        rel_i1a_oid = node.sql_value("SELECT oid FROM pg_class WHERE relname = 'i1a'")

        node.stop()

        keydir = node.datadir / "pg_tde"
        start_seg = node.datadir / "pg_wal" / start_walfile
        end_seg = node.datadir / "pg_wal" / end_walfile

        def waldump(*args):
            return node.tool("pg_tde_waldump", *args, cwd=tmp_path)

        def ok_like(cp, pat, msg):
            st.command_ok(cp, msg)
            assert re.search(pat, cp.stdout), f"{msg}: {cp.stdout!r}"

        # various ways of specifying WAL range
        st.command_fails(
            waldump("foo", "bar"), stderr_re=r'error: could not locate WAL file "foo"', msg="start file not found"
        )
        ok_like(waldump("-k", keydir, start_seg), r".", "runs with start segment specified")
        st.command_fails(
            waldump("-k", keydir, start_seg, "bar"),
            stderr_re=r'error: could not open file "bar"',
            msg="end file not found",
        )
        ok_like(waldump("-k", keydir, start_seg, end_seg), r".", "runs with start and end segment specified")
        st.command_fails(
            waldump("-p", node.datadir, "-k", keydir),
            stderr_re=r"error: no start WAL location given",
            msg="path option requires start location",
        )
        ok_like(
            waldump("-p", node.datadir, "--start", start_lsn, "--end", end_lsn, "-k", keydir),
            r".",
            "runs with path option and start and end locations",
        )
        st.command_fails(
            waldump("-k", keydir, "-p", node.datadir, "--start", start_lsn),
            stderr_re=r"error: error in WAL record at",
            msg="falling off the end of the WAL results in an error",
        )

        ok_like(waldump("--quiet", "-k", keydir, start_seg), r"^$", "no output with --quiet option")
        st.command_fails(
            waldump("--quiet", "-k", keydir, "-p", node.datadir, "--start", start_lsn),
            stderr_re=r"error: error in WAL record at",
            msg="errors are shown with --quiet",
        )

        # message that we skip data if --start is not the start of a record
        hi, lo = start_lsn.split("/")
        new_start = f"{hi}/{int(lo, 16) + 1:X}"
        cp = waldump("-k", keydir, "--start", new_start, start_seg)
        st.command_ok(cp, "runs with start segment and start LSN specified")
        info = cp.stderr if pg_major >= 17 else cp.stdout
        assert re.search(r"first record is after", info), "info message printed"

        def test_waldump(*opts):
            cp = waldump("-k", keydir, "-p", node.datadir, "--start", start_lsn, "--end", end_lsn, *opts)
            st.command_ok(cp, f"pg_waldump {opts}: runs ok")
            assert cp.stderr == "", f"pg_waldump {opts}: no stderr"
            lines = cp.stdout.split("\n")
            while lines and lines[-1] == "":
                lines.pop()
            assert len(lines) > 0, f"pg_waldump {opts}: some lines are output"
            return lines

        def count(pat, lines, negate=False):
            return sum(1 for ln in lines if bool(re.search(pat, ln)) != negate)

        lines = test_waldump()
        assert count(r"^rmgr: \w", lines, negate=True) == 0, "all output lines are rmgr lines"

        lines = test_waldump("--limit", "6")
        assert len(lines) == 6, "limit option observed"

        lines = test_waldump("--fullpage")
        assert count(r"^rmgr:.*\bFPW\b", lines, negate=True) == 0, "all output lines are FPW"

        for stats in ("--stats", "--stats=record"):
            lines = test_waldump(stats)
            assert re.search(r"WAL statistics", lines[0]), "statistics on stdout"
            assert count(r"^rmgr:", lines) == 0, "no rmgr lines output"

        lines = test_waldump("--rmgr", "Btree")
        assert count(r"^rmgr: Btree", lines, negate=True) == 0, "only Btree lines"

        lines = test_waldump("--fork", "init")
        assert count(r"fork init", lines, negate=True) == 0, "only init fork lines"

        rel = f"{default_ts_oid}/{postgres_db_oid}/{rel_t1_oid}"
        lines = test_waldump("--relation", rel)
        assert count(rf"rel {rel}", lines, negate=True) == 0, "only lines for selected relation"

        rel = f"{default_ts_oid}/{postgres_db_oid}/{rel_i1a_oid}"
        lines = test_waldump("--relation", rel, "--block", "1")
        assert count(r"\bblk 1\b", lines, negate=True) == 0, "only lines for selected block"
