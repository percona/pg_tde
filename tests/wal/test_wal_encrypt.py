import pytest

from pgtde import api
from pgtde.rewind import run_databases

KEY_INFO_SQL = "SELECT key_name, provider_name, provider_id FROM pg_tde_server_key_info()"
IN_USE = r"cannot delete provider which is currently in use"
DELETE_WAL_PROVIDER = "SELECT pg_tde_delete_global_key_provider('wal-provider')"


def ins(a, b):
    return [
        f"table public.test_wal: INSERT: id[integer]:{a} k[integer]:{a}",
        f"table public.test_wal: INSERT: id[integer]:{b} k[integer]:{b}",
    ]


EXPECTED_CHANGES = [
    "BEGIN",
    "COMMIT",
    "BEGIN",
    *ins(1, 2),
    "COMMIT",
    "BEGIN",
    *ins(3, 4),
    "COMMIT",
    "BEGIN",
    *ins(5, 6),
    "COMMIT",
    "BEGIN",
    *ins(7, 8),
    "COMMIT",
]


@pytest.mark.node_config({"wal_level": "logical"})
def test_wal_encrypt(pg_install, tde_node, keyring_obj):
    # an output plugin, not an extension: pg_available_extensions misses it
    if pg_install.pkglibdir and not any(pg_install.pkglibdir.glob("test_decoding.*")):
        pytest.skip("contrib module test_decoding not installed")
    # not tested: the server refusing to start with wal_encrypt on and no key
    node = tde_node
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "off"
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "wal-provider", scope="global")

    node.expect_error(r"principal key not configured for current database", "SELECT pg_tde_verify_server_key()")
    assert node.safe_sql(KEY_INFO_SQL) == [[None, None, None]], "should not show a valid key"

    api.create_key(node, "server-key", "wal-provider", scope="global")
    api.set_server_key(node, "server-key", "wal-provider")
    api.verify_server_key(node)
    assert node.safe_sql(KEY_INFO_SQL) == [["server-key", "wal-provider", "-1"]]
    listing = api.list_providers(node, scope="global")
    node.expect_error(IN_USE, DELETE_WAL_PROVIDER)
    assert api.list_providers(node, scope="global") == listing

    node.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = on")
    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.expect_error(IN_USE, DELETE_WAL_PROVIDER)
    assert api.list_providers(node, scope="global") == listing

    assert (
        node.sql_value("SELECT slot_name FROM pg_create_logical_replication_slot('tde_slot', 'test_decoding')")
        == "tde_slot"
    )

    node.safe_sql("CREATE TABLE test_wal (id SERIAL, k INTEGER, PRIMARY KEY (id))")
    node.safe_sql("INSERT INTO test_wal (k) VALUES (1), (2)")

    node.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = off")
    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "off"
    node.safe_sql("INSERT INTO test_wal (k) VALUES (3), (4)")

    node.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = on")
    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.safe_sql("INSERT INTO test_wal (k) VALUES (5), (6)")

    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.safe_sql("INSERT INTO test_wal (k) VALUES (7), (8)")

    changes = node.safe_sql("SELECT data FROM pg_logical_slot_get_changes('tde_slot', NULL, NULL, 'include-xids', '0')")
    assert [r[0] for r in changes] == EXPECTED_CHANGES

    node.safe_sql("SELECT pg_drop_replication_slot('tde_slot')")
    node.safe_sql("DROP EXTENSION pg_tde")


def test_server_key_moves_to_other_provider(tde_node_global, tmp_path):
    node = tde_node_global
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.safe_sql("CREATE TABLE test_wal (id int PRIMARY KEY, k int) USING heap")
    node.safe_sql("INSERT INTO test_wal SELECT i, i FROM generate_series(1, 100) i")
    node.expect_error(IN_USE, "SELECT pg_tde_delete_global_key_provider('global-provider')")

    api.add_provider(node, tmp_path / "other.keys", "other-provider", scope="global")
    api.create_key(node, "server-key2", "other-provider", scope="global")
    api.set_server_key(node, "server-key2", "other-provider")
    assert node.safe_sql(KEY_INFO_SQL) == [["server-key2", "other-provider", "-2"]]
    api.delete_provider(node, "global-provider", scope="global")
    assert [r[1] for r in api.list_providers(node, scope="global")] == ["other-provider"]

    node.restart()
    api.verify_server_key(node)
    assert node.safe_sql(KEY_INFO_SQL) == [["server-key2", "other-provider", "-2"]]
    assert node.sql_value("SELECT sum(k) FROM test_wal") == "5050"


@pytest.mark.bug("PG-1813")
def test_wal_key_tli(pg_install_dir, sw_log_dir, node_config, keyring_obj):
    run_databases(pg_install_dir, "remote", keyring_obj, restart_standby=True, config=node_config)


def _segsize(mb, **cfg):
    config = {"checkpoint_timeout": "1h", **cfg}
    return pytest.param(mb, marks=pytest.mark.node_config(config, initdb_args=[f"--wal-segsize={mb}"]), id=f"{mb}MB")


@pytest.mark.parametrize("segsize", [_segsize(1), _segsize(64, min_wal_size="256MB", max_wal_size="1GB")])
def test_wal_encrypt_segment_size(tde_node_global, segsize):
    node = tde_node_global
    assert node.sql_value("SHOW wal_segment_size") == f"{segsize}MB"
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    marker = f"segsize-{segsize}MB-marker"
    # plain heap: only WAL encryption keeps the marker off disk; enough WAL
    # after the checkpoint for crash recovery to replay over several segments
    rows, repeat = (15_000, 1) if segsize == 1 else (160_000, 30)
    node.safe_sql("CREATE TABLE seg_test (id int PRIMARY KEY, payload text) USING heap")
    node.safe_sql("CHECKPOINT")
    start = node.sql_value("SELECT pg_current_wal_lsn()")
    node.safe_sql(f"""
        INSERT INTO seg_test SELECT i, '{marker}-' || repeat(md5(i::text), {repeat}) FROM generate_series(1, {rows}) i
    """)
    written = int(node.sql_value(f"SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '{start}')"))
    assert written > 2 * segsize * 1024 * 1024

    segs = [p for p in (node.datadir / "pg_wal").iterdir() if p.is_file() and len(p.name) == 24]
    assert len(segs) >= 3
    for seg in segs:
        assert seg.stat().st_size == segsize * 1024 * 1024, seg.name
        assert marker.encode() not in seg.read_bytes(), seg.name

    node.kill()
    node.poll_start()
    assert node.sql_value("SELECT count(*) FROM seg_test") == str(rows)
    last = f"SELECT payload = '{marker}-' || repeat(md5('{rows}'), {repeat}) FROM seg_test WHERE id = {rows}"
    assert node.sql_value(last) == "t"
