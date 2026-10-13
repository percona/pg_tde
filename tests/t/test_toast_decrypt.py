def test_toast_decrypt(tde_node_db):
    node = tde_node_db
    node.safe_sql("CREATE TABLE src (f1 TEXT STORAGE EXTERNAL) USING tde_heap")
    node.safe_sql("INSERT INTO src VALUES (repeat('abcdeF', 1000))")
    assert node.sql_value("SELECT f1 FROM src") == "abcdeF" * 1000
