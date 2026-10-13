import shutil

from pgtde import api

ROWS = [["1", "5"], ["2", "6"]]


def _provider_row(path):
    return [["1", "file-vault", "file", f'{{"path" : "{path}"}}']]


def _check_readable(node):
    api.verify_key(node)
    assert node.is_encrypted("test_enc") is True
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == ROWS


def test_change_key_provider(tde_node, tmp_path):
    node = tde_node
    db1 = tmp_path / "db1.keys"
    db2 = tmp_path / "db2.keys"
    node.setup_db_key(db1, key="test-key")
    assert api.list_providers(node) == _provider_row(db1)

    node.safe_sql("""
        CREATE TABLE test_enc (id serial, k integer, PRIMARY KEY (id)) USING tde_heap;
        INSERT INTO test_enc (k) VALUES (5), (6);
    """)
    _check_readable(node)

    shutil.move(db1, db2)
    api.change_provider_file(node, "file-vault", str(db2))
    assert api.list_providers(node) == _provider_row(db2)
    _check_readable(node)

    node.restart()
    _check_readable(node)

    # move file back, restart, then change provider
    shutil.move(db2, db1)
    node.restart()

    not_found = r'key "test-key" not found in key provider "file-vault"'
    node.expect_error(not_found, "SELECT pg_tde_verify_key()")
    assert node.is_encrypted("test_enc") is True
    node.expect_error(not_found, "SELECT * FROM test_enc ORDER BY id")

    api.change_provider_file(node, "file-vault", str(db1))
    assert api.list_providers(node) == _provider_row(db1)
    _check_readable(node)

    api.drop_extension(node, cascade=True)
