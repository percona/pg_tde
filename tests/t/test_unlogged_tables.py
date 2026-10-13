def test_unlogged_tables(tde_node_db):
    node = tde_node_db
    node.safe_sql("""
        CREATE UNLOGGED TABLE t (x int PRIMARY KEY) USING tde_heap;
        INSERT INTO t SELECT generate_series(1, 4);
        CHECKPOINT;
    """)

    node.kill()
    node.poll_start()

    assert node.safe_sql("TABLE t") == []
    node.safe_sql("INSERT INTO t SELECT generate_series(1, 4)")
