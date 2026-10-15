import re

import pytest
import stormweaver.testing as st

from pgtde import api


@pytest.mark.bug("PG-2399")
def test_checksums(tde_node_factory, pg_major, keyring_obj):
    # checksums are on by default only from 18
    initdb_args = ["--no-data-checksums"] if pg_major >= 18 else []
    node = tde_node_factory("checksums", initdb_args=initdb_args)
    node.setup_db_key(keyring_obj, provider="db", key="server-key")
    node.safe_sql("CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap")
    node.safe_sql("INSERT INTO test_enc (k) VALUES (1), (2)")
    relfile = node.relation_filepath("test_enc")
    node.stop()

    st.command_ok(
        node.tool("pg_tde_checksums", "--no-sync", "--enable", node.datadir),
        "can enable checksums for encrypted tables",
    )

    node.start()
    assert node.safe_sql("SELECT * FROM test_enc") == [["1"], ["2"]]
    node.stop()

    st.corrupt_page_checksum(relfile, 0)

    cp = node.tool("pg_tde_checksums", "--check", node.datadir)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert re.search(r"Bad checksums:.*1", cp.stdout), cp.stdout
    assert re.search(r"checksum verification failed", cp.stderr), cp.stderr

    node.start()
    node.expect_error(r"invalid page in block 0 of relation", "SELECT * FROM test_enc")


def test_checksums_check_without_pg_tde_dir(tde_node_factory):
    node = tde_node_factory("fresh", start=False, extra_initdb_args=["--data-checksums"])
    assert not (node.datadir / "pg_tde").exists()

    cp = node.tool("pg_tde_checksums", "--check", node.datadir)
    st.command_ok(cp)
    assert re.search(r"Bad checksums:\s+0\n", cp.stdout), cp.stdout


def _corrupt_data(path):
    # past the page header, the stored checksum stays intact
    with open(path, "r+b") as f:
        f.seek(100)
        f.write(b"\xa5" * 16)


@pytest.mark.node_config(initdb_args=["--data-checksums"])
@pytest.mark.parametrize("wal_encrypt", [True, False], ids=["wal-encrypt", "wal-plain"])
def test_checksums_verify_server_checksums(tde_node, keyring_obj, wal_encrypt):
    node = tde_node
    node.setup_server_key(keyring_obj, wal_encrypt=wal_encrypt)
    api.create_key(node, "db-key", "global-provider", scope="global")
    api.set_key(node, "db-key", "global-provider", scope="global")
    node.restart()
    node.safe_sql("CREATE TABLE enc (id int, v text) USING tde_heap")
    node.safe_sql("INSERT INTO enc SELECT g, md5(g::text) FROM generate_series(1, 1000) g")
    node.safe_sql("CREATE TABLE plain (id int, v text) USING heap")
    node.safe_sql("INSERT INTO plain SELECT g, md5(g::text) FROM generate_series(1, 1000) g")
    node.safe_sql("CHECKPOINT")
    assert node.is_encrypted("enc")
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == ("on" if wal_encrypt else "off")
    files = {t: node.relation_filepath(t) for t in ("enc", "plain")}
    node.stop()

    cp = node.tool("pg_tde_checksums", "--check", node.datadir)
    st.command_ok(cp, "server written checksums verify")
    assert re.search(r"Bad checksums:\s+0\n", cp.stdout), cp.stdout

    for path in files.values():
        _corrupt_data(path)

    cp = node.tool("pg_tde_checksums", "--check", node.datadir)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert re.search(r"Bad checksums:\s+2\n", cp.stdout), cp.stdout
    for path in files.values():
        rel = re.escape(str(path.relative_to(node.datadir)))
        assert re.search(rf'checksum verification failed in file "[^"]*{rel}", block 0:', cp.stderr), cp.stderr
