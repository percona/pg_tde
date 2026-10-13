from pgtde import api

DEFAULT = ["-1", "file-provider", "default-key"]
NEW_DEFAULT = ["-1", "file-provider", "new-default-key"]


def test_default_principal_key(tde_node, tmp_path):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, tmp_path / "global.keys", "file-provider", scope="global")

    node.expect_error(r"principal key not configured for current database", "SELECT pg_tde_verify_default_key()")
    assert api.default_key_info(node) is None

    api.create_key(node, "default-key", "file-provider", scope="global")
    api.set_default_key(node, "default-key", "file-provider")

    assert node.safe_sql("SELECT pg_tde_verify_default_key()") == [[""]]
    assert api.default_key_info(node) == DEFAULT

    node.expect_error(
        r"cannot delete provider which is currently in use", "SELECT pg_tde_delete_global_key_provider('file-provider')"
    )
    assert node.safe_sql("SELECT id, name FROM pg_tde_list_all_global_key_providers()") == [["-1", "file-provider"]]

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
        api.create_key(node, "new-default-key", "file-provider", scope="global")
        api.set_default_key(node, "new-default-key", "file-provider")

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

    assert node.safe_sql("SELECT pg_tde_delete_global_key_provider('file-provider')") == [[""]]
