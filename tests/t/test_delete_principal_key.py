from pgtde import api

CANNOT_DELETE = r"cannot delete principal key"


def test_delete_principal_key(tde_node, file_keyring):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, file_keyring, "file-provider", scope="global")
    api.create_key(node, "defalut-key", "file-provider", scope="global")
    api.create_key(node, "test-db-key", "file-provider", scope="global")

    # no encrypted tables: delete works
    api.set_key(node, "test-db-key", "file-provider", scope="global")
    assert api.key_info(node)[2] == "test-db-key"
    api.delete_key(node)

    # encrypted table and no default key to fall back to
    api.set_key(node, "test-db-key", "file-provider", scope="global")
    node.safe_sql("CREATE TABLE test_table (id int, data text) USING tde_heap")
    res = node.expect_error(CANNOT_DELETE, "SELECT pg_tde_delete_key()")
    assert "There are encrypted tables in the database." in res.error_message
    assert "Set default principal key as fallback option" in res.error_message

    node.safe_sql("ALTER TABLE test_table SET ACCESS METHOD heap")
    api.delete_key(node)

    api.set_key(node, "test-db-key", "file-provider", scope="global")
    node.safe_sql("ALTER TABLE test_table SET ACCESS METHOD tde_heap")
    node.safe_sql("DROP TABLE test_table")
    api.delete_key(node)

    # with a default key, deleting the db key rotates to the default key
    api.set_default_key(node, "defalut-key", "file-provider")
    api.set_key(node, "test-db-key", "file-provider", scope="global")
    node.safe_sql("CREATE TABLE test_table (id int, data text) USING tde_heap")
    api.delete_key(node)
    assert api.key_info(node)[2] == "defalut-key"

    # already on the default key, nothing to fall back to
    res = node.expect_error(CANNOT_DELETE, "SELECT pg_tde_delete_key()")
    assert "There are encrypted tables in the database." in res.error_message
    res = node.expect_error(r"cannot delete default principal key", "SELECT pg_tde_delete_default_key()")
    assert "There are encrypted tables in the database with id:" in res.error_message

    api.set_key(node, "test-db-key", "file-provider", scope="global")
    api.delete_default_key(node)
    node.safe_sql("DROP TABLE test_table")
    api.delete_key(node)

    # documents current behaviour, the SQL test calls this "probably a bug":
    # deleting the default key also unsets the same key used as db/server key
    api.set_default_key(node, "test-db-key", "file-provider")
    api.set_key(node, "test-db-key", "file-provider", scope="global")
    api.set_server_key(node, "test-db-key", "file-provider")
    api.delete_default_key(node)
    assert api.key_info(node) is None
    assert api.server_key_info(node) is None

    api.delete_provider(node, "file-provider", scope="global")
    api.drop_extension(node)
