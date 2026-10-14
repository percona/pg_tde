import struct

from stormweaver.keyrings.file import FileKeyring

from pgtde import api

DEFAULT = ["-1", "global-provider", "default-key"]
NEW_DEFAULT = ["-1", "global-provider", "new-default-key"]


def test_default_key_set_verify_and_provider_in_use(tde_node, keyring_obj):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "global-provider", scope="global")

    node.expect_error(r"principal key not configured for current database", "SELECT pg_tde_verify_default_key()")
    assert api.default_key_info(node) is None

    api.create_key(node, "default-key", "global-provider", scope="global")
    api.set_default_key(node, "default-key", "global-provider")

    assert node.safe_sql("SELECT pg_tde_verify_default_key()") == [[""]]
    assert api.default_key_info(node) == DEFAULT

    node.expect_error(
        r"cannot delete provider which is currently in use",
        "SELECT pg_tde_delete_global_key_provider('global-provider')",
    )
    assert node.safe_sql("SELECT id, name FROM pg_tde_list_all_global_key_providers()") == [["-1", "global-provider"]]

    # key rotation
    node.safe_sql("CREATE DATABASE other")
    with node.connect(db="other") as other:
        api.create_extension(other)

        for conn in (node, other):
            assert api.key_info(conn) is None
            conn.safe_sql("""
                CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
                INSERT INTO test_enc (x) VALUES (1), (2);
            """)
            assert api.key_info(conn) == DEFAULT

        node.safe_sql("CHECKPOINT")
        api.create_key(node, "new-default-key", "global-provider", scope="global")
        api.set_default_key(node, "new-default-key", "global-provider")

        assert api.key_info(node) == NEW_DEFAULT
        assert api.key_info(other) == NEW_DEFAULT

    node.restart()

    with node.connect(db="other") as other:
        for conn in (node, other):
            assert conn.safe_sql("SELECT * FROM test_enc ORDER BY x") == [["1"], ["2"]]

        # dropping default keys
        other.safe_sql("DROP TABLE test_enc")
        other.expect_error(
            r"cannot delete default principal key\n"
            r"HINT:  There are encrypted tables in the database with id: 5",
            "SELECT pg_tde_delete_default_key()",
        )

        node.safe_sql("DROP TABLE test_enc")
        assert other.safe_sql("SELECT pg_tde_delete_default_key()") == [[""]]

    assert node.safe_sql("SELECT pg_tde_delete_global_key_provider('global-provider')") == [[""]]


CANNOT_DELETE = r"cannot delete principal key"


def test_delete_key_needs_default_key_with_encrypted_tables(tde_node, keyring_obj):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "global-provider", scope="global")
    api.create_key(node, "defalut-key", "global-provider", scope="global")
    api.create_key(node, "test-db-key", "global-provider", scope="global")

    # no encrypted tables: delete works
    api.set_key(node, "test-db-key", "global-provider", scope="global")
    assert api.key_info(node)[2] == "test-db-key"
    api.delete_key(node)
    assert api.key_info(node) is None

    # encrypted table and no default key to fall back to
    api.set_key(node, "test-db-key", "global-provider", scope="global")
    node.safe_sql("CREATE TABLE test_table (id int, data text) USING tde_heap")
    res = node.expect_error(CANNOT_DELETE, "SELECT pg_tde_delete_key()")
    assert "There are encrypted tables in the database." in res.error_message
    assert "Set default principal key as fallback option" in res.error_message

    node.safe_sql("ALTER TABLE test_table SET ACCESS METHOD heap")
    api.delete_key(node)

    api.set_key(node, "test-db-key", "global-provider", scope="global")
    node.safe_sql("ALTER TABLE test_table SET ACCESS METHOD tde_heap")
    node.safe_sql("DROP TABLE test_table")
    api.delete_key(node)

    # with a default key, deleting the db key rotates to the default key
    api.set_default_key(node, "defalut-key", "global-provider")
    api.set_key(node, "test-db-key", "global-provider", scope="global")
    node.safe_sql("CREATE TABLE test_table (id int, data text) USING tde_heap")
    api.delete_key(node)
    assert api.key_info(node)[2] == "defalut-key"

    # already on the default key, nothing to fall back to
    res = node.expect_error(CANNOT_DELETE, "SELECT pg_tde_delete_key()")
    assert "There are encrypted tables in the database." in res.error_message
    res = node.expect_error(r"cannot delete default principal key", "SELECT pg_tde_delete_default_key()")
    assert "There are encrypted tables in the database with id:" in res.error_message

    api.set_key(node, "test-db-key", "global-provider", scope="global")
    api.delete_default_key(node)
    assert api.default_key_info(node) is None
    node.safe_sql("DROP TABLE test_table")
    api.delete_key(node)

    # documents current behaviour, the SQL test calls this "probably a bug":
    # deleting the default key also unsets the same key used as db/server key
    api.set_default_key(node, "test-db-key", "global-provider")
    api.set_key(node, "test-db-key", "global-provider", scope="global")
    api.set_server_key(node, "test-db-key", "global-provider")
    api.delete_default_key(node)
    assert api.key_info(node) is None
    assert api.server_key_info(node) is None

    api.delete_provider(node, "global-provider", scope="global")
    api.drop_extension(node)


# TDE_KEY_NAME_LEN + MAX_KEY_DATA_SIZE, see src/include/keyring/keyring_api.h
KEY_LEN_OFFSET = 256 + 32


def _corrupt(path):
    with open(path, "r+b") as f:
        f.seek(KEY_LEN_OFFSET)
        f.write(struct.pack("=I", 0))
        f.seek(KEY_LEN_OFFSET, 1)
        f.write(struct.pack("=I", 0xFFFFFFFF))


def _set_key_fails(node, key, warning):
    off = node.log_offset()
    res = node.expect_error(
        rf'failed to retrieve principal key "{key}" from key provider "test-file-provider"',
        f"SELECT pg_tde_set_key_using_database_key_provider('{key}', 'test-file-provider')",
    )
    assert "Invalid key" in res.error_message
    node.wait_for_log(rf"WARNING:  {warning}", offset=off, timeout=5)


def test_key_validation(tde_node, tmp_path):
    node = tde_node
    kr = FileKeyring(tmp_path / "db.keys")
    api.create_extension(node)
    api.add_provider(node, kr, "test-file-provider")
    api.create_key(node, "key1", "test-file-provider")
    api.create_key(node, "key2", "test-file-provider")
    _corrupt(kr.path)

    _set_key_fails(node, "key1", r"invalid key: data length is zero")
    _set_key_fails(node, "key2", r'invalid key: unsupported key length "4294967295"')
