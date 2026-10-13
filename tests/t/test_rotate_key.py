from pgtde import api

ROWS = [["1", "5"], ["2", "6"]]


def _read(node):
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == ROWS


def _rotate(node, key, provider, scope, info):
    api.create_key(node, key, provider, scope=scope)
    api.set_key(node, key, provider, scope=scope)
    _read(node)
    node.restart()
    assert api.key_info(node) == info
    assert api.server_key_info(node) is None
    _read(node)


def test_rotate_key(tde_node, tmp_path):
    node = tde_node
    db1 = tmp_path / "db1.keys"
    db2 = tmp_path / "db2.keys"
    api.create_extension(node)
    api.add_provider(node, db1, "file-vault")
    api.add_provider(node, db2, "file-2")
    api.add_provider(node, tmp_path / "global2.keys", "file-2", scope="global")
    api.add_provider(node, tmp_path / "global3.keys", "file-3", scope="global")

    assert api.list_providers(node) == [
        ["1", "file-vault", "file", f'{{"path" : "{db1}"}}'],
        ["2", "file-2", "file", f'{{"path" : "{db2}"}}'],
    ]

    api.create_key(node, "test-db-key", "file-vault")
    api.set_key(node, "test-db-key", "file-vault")
    node.safe_sql("""
        CREATE TABLE test_enc (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap;
        INSERT INTO test_enc (k) VALUES (5), (6);
    """)
    _read(node)

    _rotate(node, "rotated-key1", "file-vault", "database", ["1", "file-vault", "rotated-key1"])
    _rotate(node, "rotated-key2", "file-2", "database", ["2", "file-2", "rotated-key2"])
    _rotate(node, "rotated-key", "file-3", "global", ["-2", "file-3", "rotated-key"])
    _rotate(node, "rotated-keyX", "file-2", "global", ["-1", "file-2", "rotated-keyX"])

    node.safe_sql("ALTER SYSTEM SET pg_tde.inherit_global_providers = off")
    node.restart()

    disabled = r"usage of global key providers is disabled"
    node.expect_error(disabled, "SELECT pg_tde_create_key_using_global_key_provider('rotated-keyX2', 'file-2')")
    node.expect_error(disabled, "SELECT pg_tde_set_key_using_global_key_provider('rotated-keyX2', 'file-2')")
    assert api.key_info(node) == ["-1", "file-2", "rotated-keyX"]
    assert api.server_key_info(node) is None

    api.set_key(node, "rotated-key2", "file-2")
    assert api.key_info(node) == ["2", "file-2", "rotated-key2"]
    assert api.server_key_info(node) is None

    node.safe_sql("DROP TABLE test_enc")
    node.safe_sql("ALTER SYSTEM RESET pg_tde.inherit_global_providers")
    node.restart()
    api.drop_extension(node, cascade=True)
