import pytest

from pgtde import api

KEY_INFO_SQL = "SELECT key_name, provider_name, provider_id FROM pg_tde_server_key_info()"


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


def test_wal_encrypt(pg_install, tde_node_factory, keyring_obj):
    # an output plugin, not an extension: pg_available_extensions misses it
    if pg_install.pkglibdir and not any(pg_install.pkglibdir.glob("test_decoding.*")):
        pytest.skip("contrib module test_decoding not installed")
    # not tested: the server refusing to start with wal_encrypt on and no key
    node = tde_node_factory("main", config={"wal_level": "logical"})
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "file-keyring-010", scope="global")

    node.expect_error(r"principal key not configured for current database", "SELECT pg_tde_verify_server_key()")
    assert node.safe_sql(KEY_INFO_SQL) == [[None, None, None]], "should not show a valid key"

    api.create_key(node, "server-key", "file-keyring-010", scope="global")
    api.set_server_key(node, "server-key", "file-keyring-010")
    api.verify_server_key(node)
    assert node.safe_sql(KEY_INFO_SQL) == [["server-key", "file-keyring-010", "-1"]]

    node.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = on")
    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"

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
