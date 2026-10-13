from pgtde import api

# regression for the ALTER INDEX ... ATTACH PARTITION event trigger handling
SETUP = """
    SET default_table_access_method = 'tde_heap';
    CREATE TABLE concur_reindex_part (c1 int, c2 int) PARTITION BY RANGE (c1);
    CREATE TABLE concur_reindex_part_0 PARTITION OF concur_reindex_part
        FOR VALUES FROM (0) TO (10) PARTITION BY list (c2);
    CREATE TABLE concur_reindex_part_0_1 PARTITION OF concur_reindex_part_0 FOR VALUES IN (1);
    CREATE TABLE concur_reindex_part_0_2 PARTITION OF concur_reindex_part_0 FOR VALUES IN (2);
    CREATE TABLE concur_reindex_part_10 PARTITION OF concur_reindex_part
        FOR VALUES FROM (10) TO (20) PARTITION BY list (c2);
    CREATE INDEX concur_reindex_part_index ON ONLY concur_reindex_part (c1);
    CREATE INDEX concur_reindex_part_index_0 ON ONLY concur_reindex_part_0 (c1);
    ALTER INDEX concur_reindex_part_index ATTACH PARTITION concur_reindex_part_index_0;
    CREATE INDEX concur_reindex_part_index_10 ON ONLY concur_reindex_part_10 (c1);
    ALTER INDEX concur_reindex_part_index ATTACH PARTITION concur_reindex_part_index_10;
    CREATE INDEX concur_reindex_part_index_0_1 ON ONLY concur_reindex_part_0_1 (c1);
    ALTER INDEX concur_reindex_part_index_0 ATTACH PARTITION concur_reindex_part_index_0_1;
    CREATE INDEX concur_reindex_part_index_0_2 ON ONLY concur_reindex_part_0_2 (c1);
    ALTER INDEX concur_reindex_part_index_0 ATTACH PARTITION concur_reindex_part_index_0_2;
"""


def test_alter_index(tde_node_db):
    node = tde_node_db
    node.safe_sql(SETUP)

    tree = node.safe_sql(
        "SELECT relid::text, parentrelid::text FROM pg_partition_tree('concur_reindex_part_index') ORDER BY 1"
    )
    p = "concur_reindex_part_index"
    assert tree == [[p, None], [f"{p}_0", p], [f"{p}_0_1", f"{p}_0"], [f"{p}_0_2", f"{p}_0"], [f"{p}_10", p]]

    node.safe_sql("DROP TABLE concur_reindex_part")
    api.delete_key(node)
    api.delete_provider(node, "file-vault")
