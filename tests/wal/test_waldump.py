import re
import struct
import tempfile

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.wal import wal_contains

MARKER = "waldump-plaintext-marker"

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
    f"INSERT INTO t1 VALUES (default, '{MARKER}')",
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


@pytest.mark.node_config(
    {
        "autovacuum": "off",
        "checkpoint_timeout": "1h",
        # for standbydesc
        "archive_mode": "on",
        "archive_command": "",
        # for XLOG_HEAP_TRUNCATE
        "wal_level": "logical",
    }
)
def test_waldump_basic(tde_node, keyring_obj, pg_major, tmp_path, tblspc_dir):
    node = tde_node
    node.setup_server_key(keyring_obj, provider="wal-provider", key="server-key")
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
    xid = node.sql_value(f"SELECT xmin FROM t1 WHERE b = '{MARKER}'")

    node.stop()
    assert not wal_contains(node, MARKER, flush=False)

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

    def run_waldump(*opts):
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

    lines = run_waldump()
    assert count(r"^rmgr: \w", lines, negate=True) == 0, "all output lines are rmgr lines"

    lines = run_waldump("--limit", "6")
    assert len(lines) == 6, "limit option observed"

    lines = run_waldump("--fullpage")
    assert count(r"^rmgr:.*\bFPW\b", lines, negate=True) == 0, "all output lines are FPW"

    for stats in ("--stats", "--stats=record"):
        lines = run_waldump(stats)
        assert re.search(r"WAL statistics", lines[0]), "statistics on stdout"
        assert count(r"^rmgr:", lines) == 0, "no rmgr lines output"
        if stats == "--stats=record":
            assert count(r"^Heap/INSERT\s", lines) > 0, "per record type stats"

    lines = run_waldump("--xid", xid)
    assert count(rf"^rmgr: .*\btx: +{xid},", lines, negate=True) == 0, "only lines of the selected xid"

    lines = run_waldump("--bkp-details")
    assert count(r"^\s+blkref #\d+: rel \d+/\d+/\d+", lines) > 0, "block references printed"

    lines = run_waldump("--rmgr", "Btree")
    assert count(r"^rmgr: Btree", lines, negate=True) == 0, "only Btree lines"

    lines = run_waldump("--fork", "init")
    assert count(r"fork init", lines, negate=True) == 0, "only init fork lines"

    rel = f"{default_ts_oid}/{postgres_db_oid}/{rel_t1_oid}"
    lines = run_waldump("--relation", rel)
    assert count(rf"rel {rel}", lines, negate=True) == 0, "only lines for selected relation"

    rel = f"{default_ts_oid}/{postgres_db_oid}/{rel_i1a_oid}"
    lines = run_waldump("--relation", rel, "--block", "1")
    assert count(r"\bblk 1\b", lines, negate=True) == 0, "only lines for selected block"


# TLI-LSNh-LSNl.TBLSPCOID.DBOID.NODEOID.BLKNO[_fork]
FILE_RE = re.compile(
    r"^[0-9A-F]{8}-([0-9A-F]{8})-([0-9A-F]{8})[.][0-9]+[.][0-9]+[.][0-9]+[.][0-9]+(?:_vm|_init|_fsm|_main)?$"
)


REL_SQL = """
    SELECT format('%s/%s/%s', CASE WHEN c.reltablespace = 0 THEN d.dattablespace ELSE c.reltablespace END,
                  d.oid, pg_relation_filenode(c.oid))
    FROM pg_class c, pg_database d
    WHERE c.oid = {rel} AND d.datname = current_database()
"""


def block_lsn(path, blocksize):
    block = path.read_bytes()[:blocksize]
    assert len(block) == blocksize, f"could not read block from {path}"
    hi, lo = struct.unpack("<II", block[:8])
    return f"{hi:08X}", f"{lo:08X}"


@pytest.mark.node_config({"wal_level": "replica", "max_wal_senders": "4"})
def test_waldump_fullpage(tde_node, keyring_obj, tmp_path):
    node = tde_node
    node.setup_server_key(keyring_obj, provider="wal-provider", key="server-key")
    api.create_key(node, "db-key", "wal-provider", scope="global")
    api.set_key(node, "db-key", "wal-provider", scope="global")
    node.db.add_config({"pg_tde.wal_encrypt": "on"})
    node.restart()

    # data/WAL with full pages in it
    node.safe_sql("SELECT 'init' FROM pg_create_physical_replication_slot('regress_pg_waldump_slot', true, false)")
    node.safe_sql(f"CREATE TABLE test_table USING tde_heap AS SELECT a, '{MARKER}' AS b FROM generate_series(1,100) a")
    # force FPWs on the next writes
    node.safe_sql("CHECKPOINT")
    node.safe_sql("UPDATE test_table SET a = a + 1")

    [[walfile_name, blocksize]] = node.safe_sql(
        "SELECT pg_walfile_name(pg_switch_wal()), current_setting('block_size')"
    )
    relation = node.sql_value(REL_SQL.format(rel="'test_table'::regclass"))
    assert node.is_encrypted("test_table")

    walfile = node.datadir / "pg_wal" / walfile_name
    assert walfile.is_file(), "Got a WAL file"

    raw = tmp_path / "raw"
    st.command_ok(
        node.tool(
            "pg_tde_waldump",
            "--quiet",
            "-k",
            node.datadir / "pg_tde",
            "--save-fullpage",
            raw,
            "--relation",
            relation,
            walfile,
        ),
        "pg_waldump with --save-fullpage runs",
    )

    assert not wal_contains(node, MARKER, flush=False)
    assert any(MARKER.encode() in p.read_bytes() for p in raw.glob("*")), "saved pages are decrypted"

    file_count = 0
    for path in sorted(raw.glob("*")):
        m = FILE_RE.search(path.name)
        assert m, f"verify filename format for file {path.name}"
        file_count += 1
        hi_bk, lo_bk = block_lsn(path, int(blocksize))
        # the LSN on the block comes before the file's LSN
        assert m.group(1) + m.group(2) > hi_bk + lo_bk, "LSN stored in the file precedes the one stored in the block"

    assert file_count > 0, "verify that at least one block has been saved"


@pytest.mark.node_config({"autovacuum": "off", "checkpoint_timeout": "1h"})
def test_waldump_tde_rmgr(tde_node, keyring_obj, tools):
    node = tde_node
    start_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")

    # XLOG_TDE_INSTALL_EXTENSION, XLOG_TDE_WRITE_KEY_PROVIDER,
    # XLOG_TDE_ADD_PRINCIPAL_KEY
    node.setup_server_key(keyring_obj, provider="wal-provider", key="server-key")

    end_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")
    node.stop()

    log = node.server_log.read_text(errors="replace")
    assert re.search(r'registered custom resource manager "pg_tde" with ID 140', log), "rmgr registered at startup"

    def run_waldump(*opts, keyring=True):
        cp = node.tool(
            "pg_tde_waldump",
            *(["-k", node.datadir / "pg_tde"] if keyring else []),
            "-p",
            node.datadir,
            "--start",
            start_lsn,
            "--end",
            end_lsn,
            *opts,
        )
        st.command_ok(cp, f"pg_tde_waldump {opts}: runs ok")
        assert cp.stderr == "", f"pg_tde_waldump {opts}: no stderr"
        lines = cp.stdout.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        assert len(lines) > 0, f"pg_tde_waldump {opts}: some lines are output"
        return lines

    def count(pat, lines):
        return sum(1 for ln in lines if re.search(pat, ln))

    lines = run_waldump()
    assert count(r"^rmgr: pg_tde\b", lines) > 0, "pg_tde rmgr lines are present"
    assert count(r"^rmgr: custom140\b", lines) == 0, "no unresolved custom140 rmgr lines"
    assert count(r"^rmgr: pg_tde\b.*\bdesc: UNKNOWN\b", lines) == 0, (
        "no unresolved UNKNOWN description for pg_tde records"
    )
    for desc in ("INSTALL_EXTENSION", "WRITE_KEY_PROVIDER", "ADD_PRINCIPAL_KEY"):
        assert count(rf"^rmgr: pg_tde\b.*\bdesc: {desc}\b", lines) > 0, f"{desc} record is described"
    assert run_waldump(keyring=False) == lines, "plain WAL decodes the same without -k"

    cp = tools.run("pg_tde_waldump", "--rmgr", "list")
    st.command_ok(cp, "pg_tde_waldump --rmgr=list runs ok")
    assert re.search(r"^pg_tde$", cp.stdout, re.M), "pg_tde is listed as a known rmgr"

    lines = run_waldump("--rmgr", "pg_tde")
    assert len(lines) > 0, "at least one pg_tde record found when filtering by name"
    assert len(lines) == count(r"^rmgr: pg_tde\b", lines), "only pg_tde lines with --rmgr=pg_tde"

    lines_legacy = run_waldump("--rmgr", "custom140")
    assert len(lines_legacy) == count(r"^rmgr: pg_tde\b", lines_legacy), (
        "only pg_tde lines with legacy --rmgr=custom140"
    )
    assert lines == lines_legacy, "--rmgr=pg_tde and --rmgr=custom140 select the same records"


KINDS_WORKLOAD = [
    "CREATE TABLE enc (id int, arr int[], n int, lbl text) USING tde_heap",
    "CREATE INDEX enc_btree ON enc USING btree (id)",
    "CREATE INDEX enc_hash ON enc USING hash (lbl)",
    "CREATE INDEX enc_gin ON enc USING gin (arr)",
    "CREATE INDEX enc_brin ON enc USING brin (n)",
    "INSERT INTO enc SELECT g, ARRAY[g, g + 1], g % 100, 'enc-' || g || '-{m}' FROM generate_series(1, 500) g",
    "CREATE TABLE plain (id int, lbl text) USING heap",
    "INSERT INTO plain SELECT g, 'plain-' || g || '-{m}' FROM generate_series(1, 100) g",
    "CREATE TABLE toasty (id int, payload text) USING tde_heap",
    "ALTER TABLE toasty ALTER COLUMN payload SET STORAGE EXTERNAL",
    "INSERT INTO toasty SELECT g, repeat('toast-{m}-', 400) FROM generate_series(1, 20) g",
    "CREATE TABLE parts (id int, region text, lbl text) PARTITION BY LIST (region)",
    "CREATE TABLE parts_e PARTITION OF parts FOR VALUES IN ('east') USING tde_heap",
    "CREATE TABLE parts_w PARTITION OF parts FOR VALUES IN ('west') USING tde_heap",
    """INSERT INTO parts SELECT g, CASE g % 2 WHEN 0 THEN 'east' ELSE 'west' END, 'part-' || g || '-{m}'
       FROM generate_series(1, 200) g""",
    "CREATE MATERIALIZED VIEW mv USING tde_heap AS SELECT id, lbl FROM enc WHERE id % 2 = 0",
    "REFRESH MATERIALIZED VIEW mv",
]


@pytest.mark.node_config({"autovacuum": "off", "checkpoint_timeout": "1h"})
def test_waldump_encrypted_relation_kinds(tde_node, keyring_obj):
    node = tde_node
    node.setup_server_key(keyring_obj, wal_encrypt=True)
    api.create_key(node, "db-key", "global-provider", scope="global")
    api.set_key(node, "db-key", "global-provider", scope="global")
    node.restart()
    # keeps the WAL across the checkpoints below
    node.safe_sql("SELECT 'init' FROM pg_create_physical_replication_slot('waldump_slot', true, false)")
    start_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")

    for sql in KINDS_WORKLOAD:
        node.safe_sql(sql.format(m=MARKER))
    rels = {
        r: node.sql_value(REL_SQL.format(rel=f"'{r}'::regclass")) for r in ("enc", "plain", "parts_e", "parts_w", "mv")
    }
    assert node.is_encrypted("mv")
    rels["toast"] = node.sql_value(REL_SQL.format(rel="(SELECT reltoastrelid FROM pg_class WHERE relname = 'toasty')"))

    node.safe_sql("CREATE DATABASE db2")
    with node.connect(db="db2") as conn:
        api.create_extension(conn)
        api.create_key(conn, "db2-key", "global-provider", scope="global")
        api.set_key(conn, "db2-key", "global-provider", scope="global")
        conn.safe_sql("CREATE TABLE enc2 (id int, lbl text) USING tde_heap")
        conn.safe_sql(f"INSERT INTO enc2 SELECT g, 'db2-' || g || '-{MARKER}' FROM generate_series(1, 100) g")
        rels["db2"] = conn.sql_value(REL_SQL.format(rel="'enc2'::regclass"))
    end_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")

    # plain heap too: WAL encryption covers the whole stream
    assert not wal_contains(node, MARKER)
    node.stop()

    def waldump(*opts, keyring=True):
        keydir = ["-k", node.datadir / "pg_tde"] if keyring else []
        return node.tool("pg_tde_waldump", *keydir, "-p", node.datadir, "--start", start_lsn, "--end", end_lsn, *opts)

    cp = waldump()
    st.command_ok(cp, "decodes with -k")
    assert cp.stderr == ""
    rmgrs = set(re.findall(r"^rmgr: (\w+)", cp.stdout, re.M))
    assert {"Heap", "Btree", "Hash", "Gin", "BRIN", "pg_tde"} <= rmgrs, rmgrs

    for kind, rel in rels.items():
        cp = waldump("--relation", rel)
        st.command_ok(cp, f"{kind}: --relation runs")
        assert re.search(rf"^rmgr: Heap2? .*\brel {re.escape(rel)}\b", cp.stdout, re.M), f"{kind}: heap records"

    cp = waldump(keyring=False)
    st.command_fails(
        cp,
        stderr_re=rf"error: could not find a valid record after {re.escape(start_lsn)}",
        msg="no -k: encrypted WAL is not decoded",
    )
    assert cp.stdout == ""
