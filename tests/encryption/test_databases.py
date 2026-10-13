from pgtde import api


def test_create_database(tde_node, tmp_path):
    node = tde_node
    api.create_extension(node)
    node.safe_sql("CREATE DATABASE template_db")
    with node.connect(db="template_db") as conn:
        api.create_extension(conn)
        api.add_provider(conn, tmp_path / "template_provider.per", "file-vault")
        api.create_key(conn, "test-db-key", "file-vault")
        api.set_key(conn, "test-db-key", "file-vault")
        conn.safe_sql("""
            CREATE TABLE test_enc (id serial PRIMARY KEY, x int) USING tde_heap;
            CREATE TABLE test_plain (id serial PRIMARY KEY, x int) USING heap;
            INSERT INTO test_enc (x) VALUES (10), (20);
            INSERT INTO test_plain (x) VALUES (30), (40);
        """)

    # TODO in the SQL test: no-default-key case is not covered
    api.add_provider(node, tmp_path / "template_provider_global.per", "global-file-vault", scope="global")
    api.create_key(node, "default-key", "global-file-vault", scope="global")
    api.set_default_key(node, "default-key", "global-file-vault")

    node.safe_sql("CREATE DATABASE new_db TEMPLATE template_db")
    with node.connect(db="new_db") as conn:
        for t, enc, x in (("test_enc", True, 25), ("test_plain", False, 45)):
            conn.safe_sql(f"INSERT INTO {t} (x) VALUES ({x})")
            assert conn.sql_value(f"SELECT count(*) FROM {t}") == "3"
            for rel in (t, f"{t}_pkey", f"{t}_id_seq"):
                assert api.is_encrypted(conn, rel) is enc, rel

    res = node.expect_error(
        r"The FILE_COPY strategy cannot be used when there are encrypted objects "
        r"in the template database: 3 objects found",
        "CREATE DATABASE new_db_file_copy TEMPLATE template_db STRATEGY FILE_COPY",
    )
    assert "Use the WAL_LOG strategy instead." in res.error_message

    with node.connect(db="template_db") as conn:
        conn.safe_sql("DROP TABLE test_enc")
    node.safe_sql("CREATE DATABASE new_db_file_copy TEMPLATE template_db STRATEGY FILE_COPY")

    for db in ("new_db_file_copy", "new_db", "template_db"):
        node.safe_sql(f"DROP DATABASE {db}")
    api.delete_default_key(node)
    api.delete_provider(node, "global-file-vault", scope="global")
