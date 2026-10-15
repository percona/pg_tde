import re

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.checks import setup_error
from pgtde.wal import wal_contains, wal_segments


def _keyed_table(node, rows):
    api.create_key(node, "db-key", "global-provider", scope="global")
    api.set_key(node, "db-key", "global-provider", scope="global")
    node.safe_sql("CREATE TABLE t (id serial PRIMARY KEY, payload text) USING tde_heap")
    node.safe_sql(f"INSERT INTO t (payload) SELECT md5(g::text) FROM generate_series(1, {rows}) g")
    node.safe_sql("CHECKPOINT")


def _snapshot(node):
    files = [node.datadir / "global" / "pg_control", *sorted((node.datadir / "pg_tde").rglob("*"))]
    wal = sorted(p.name for p in (node.datadir / "pg_wal").iterdir())
    return {str(p): p.read_bytes() for p in files if p.is_file()}, wal


def _reset(node):
    _keyed_table(node, 5000)
    node.stop()
    cp = node.tool("pg_tde_resetwal", "-f", "-D", node.datadir)
    st.command_ok(cp)
    assert re.search(r"^Write-ahead log reset$", cp.stdout, re.M), cp.stdout
    node.start()


def _plaintext_segments(node, needle):
    return [p.name for p in wal_segments(node) if needle.encode() in p.read_bytes()]


def test_resetwal_keeps_encrypted_data(tde_node_global):
    node = tde_node_global
    _reset(node)
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    assert node.sql_value("SELECT count(*) FROM t") == "5000"
    assert node.is_encrypted("t")

    # replay of WAL written after the reset
    node.safe_sql("INSERT INTO t (payload) VALUES ('after-reset')")
    node.kill()
    node.poll_start()
    assert node.sql_value("SELECT count(*) FROM t WHERE payload = 'after-reset'") == "1"
    node.safe_sql("INSERT INTO t (payload) VALUES ('after-recovery-marker')")
    assert not wal_contains(node, "after-recovery-marker")


@pytest.mark.bug("PG-2862")
@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="PG-2862: first WAL page after pg_tde_resetwal written unencrypted"
)
def test_resetwal_first_wal_encrypted(tde_node_global):
    node = tde_node_global
    _reset(node)
    node.safe_sql("INSERT INTO t (payload) VALUES ('after-reset-marker')")
    # no checkpoint or switch, a later write of the page hides the leak
    leaked = _plaintext_segments(node, "after-reset-marker")
    node.kill()
    node.poll_start()
    leaked += _plaintext_segments(node, "after-reset-marker")
    assert not leaked, leaked


def test_resetwal_dry_run_changes_nothing(tde_node_global):
    node = tde_node_global
    _keyed_table(node, 10)
    node.stop()
    before = _snapshot(node)

    cp = node.tool("pg_tde_resetwal", "-n", "-D", node.datadir)
    st.command_ok(cp)
    assert "Current pg_control values:" in cp.stdout, cp.stdout
    assert "Values to be changed:" in cp.stdout, cp.stdout
    assert _snapshot(node) == before

    node.start()
    assert node.sql_value("SELECT count(*) FROM t") == "10"
    assert node.is_encrypted("t")


@pytest.mark.bug("PG-2870")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="PG-2870: pg_tde_resetwal with relative datadir breaks WAL encrypted cluster",
)
def test_resetwal_relative_datadir(tde_node_global):
    node = tde_node_global

    def setup():
        _keyed_table(node, 100)
        node.stop()
        cp = node.tool("pg_tde_resetwal", "-f", node.datadir.name, cwd=node.datadir.parent)
        st.command_ok(cp)
        return node.log_offset()

    offset = setup_error(setup)
    try:
        node.start()
    except RuntimeError:
        log = node.log_since(offset)
        if "invalid magic number" in log and "could not locate a valid checkpoint record" in log:
            raise AssertionError("server does not start after pg_tde_resetwal with a relative datadir") from None
        raise
    assert node.sql_value("SELECT count(*) FROM t") == "100"
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
