from t.test_tde_heap import check_tde_heap


def test_tde_heap_aes_256(tde_node_db):
    node = tde_node_db
    node.safe_sql("CREATE TABLE test_enc0 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap")
    node.safe_sql("INSERT INTO test_enc0 (k) VALUES ('multitude'), ('multitudinous')")
    rows = [["1", "multitude"], ["2", "multitudinous"]]
    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == rows

    node.db.add_config({"pg_tde.cipher": "aes_256"})
    node.restart()

    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == rows
    node.safe_sql("INSERT INTO test_enc0 (k) VALUES ('multitudinously'), ('multitudinousness')")
    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == [
        *rows,
        ["3", "multitudinously"],
        ["4", "multitudinousness"],
    ]

    check_tde_heap(node)
