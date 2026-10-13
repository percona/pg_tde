from pgtde import api


def test_tablespace(tde_node_db, keyring_obj):
    node = tde_node_db
    node.safe_sql("""
        CREATE TABLE test (num1 bigint, num2 double precision, t text) USING tde_heap;
        INSERT INTO test (num1, num2, t) SELECT i, random(), 'text' FROM generate_series(1, 10) s(i);
        CREATE INDEX test_idx ON test (num1);
        SET allow_in_place_tablespaces = true;
    """)
    node.safe_sql("CREATE TABLESPACE test_tblspace LOCATION ''")
    node.safe_sql("ALTER TABLE test SET TABLESPACE test_tblspace")
    assert node.sql_value("SELECT count(*) FROM test") == "10"
    node.safe_sql("ALTER TABLE test SET TABLESPACE pg_default")
    node.safe_sql("REINDEX (TABLESPACE test_tblspace, CONCURRENTLY) TABLE test")
    node.safe_sql("INSERT INTO test VALUES (110, 2)")
    assert node.safe_sql("SELECT num1, num2, t FROM test WHERE num1 = 110") == [["110", "2", None]]
    assert api.is_encrypted(node, "test") is True
    assert api.is_encrypted(node, "test_idx") is True

    # refuse to move a database with encrypted objects in its default tablespace
    node.safe_sql("CREATE TABLESPACE test_tblspace2 LOCATION ''")
    node.safe_sql("CREATE DATABASE move_test")
    with node.connect(db="move_test") as conn:
        api.create_extension(conn)
        api.add_provider(conn, keyring_obj, "file-vault")
        api.create_key(conn, "test-db-key2", "file-vault")
        api.set_key(conn, "test-db-key2", "file-vault")
        conn.safe_sql("CREATE TABLE test2 (x int) USING tde_heap TABLESPACE test_tblspace2")
    node.safe_sql("ALTER DATABASE move_test SET TABLESPACE test_tblspace")

    with node.connect(db="move_test") as conn:
        conn.safe_sql("CREATE TABLE test3 (x int) USING tde_heap")
    res = node.expect_error(
        r"SET TABLESPACE cannot be used when there are encrypted objects in the default .* "
        r"of the database: 1 object found",
        "ALTER DATABASE move_test SET TABLESPACE pg_default",
    )
    assert "Move every object separately" in res.error_message

    node.safe_sql("DROP DATABASE move_test")
    node.safe_sql("DROP TABLE test")
    node.safe_sql("DROP TABLESPACE test_tblspace")
    node.safe_sql("DROP TABLESPACE test_tblspace2")
