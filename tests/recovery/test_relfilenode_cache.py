import pytest

from pgtde import api

# from upstream src/test/recovery/t/032_relfilenode_reuse.pl
EVICT = "SELECT SUM(pg_prewarm(oid)) warmed_buffers FROM pg_class WHERE pg_relation_filenode(oid) != 0"


@pytest.mark.node_config({"full_page_writes": "off", "shared_buffers": "1MB"})
def test_reuse_relfilenode_in_cache(tde_node, keyring_obj):
    node = tde_node
    api.require_contrib(node, "pg_prewarm")
    node.setup_default_key(keyring_obj, provider="global-keyring", key="default-key")

    # template with a table larger than shared buffers so relfilenodes get
    # reused, fixed OID to avoid clashing with the test database
    node.safe_sql("CREATE DATABASE conflict_db_template OID = 50000")
    with node.connect(db="conflict_db_template") as tpl:
        tpl.safe_sql("""
            CREATE EXTENSION pg_tde;
            CREATE TABLE large(id serial primary key, dataa text, datab text)
                USING tde_heap;
            INSERT INTO large(dataa, datab)
                SELECT g.i::text, 1 FROM generate_series(1, 4000) g(i);
        """)

    create_db = "CREATE DATABASE conflict_db TEMPLATE conflict_db_template OID = 50001"
    node.safe_sql(create_db)

    node.safe_sql("""
        CREATE EXTENSION pg_prewarm;
        CREATE TABLE replace_sb (data text);
        INSERT INTO replace_sb(data)
            SELECT random()::text FROM generate_series(1, 15000);
    """)

    # holds SMgrRelation structs open across txn boundary
    with node.connect() as bg:
        bg.safe_sql("BEGIN")

        with node.connect(db="conflict_db") as c:
            c.safe_sql("UPDATE large SET datab = 1")
        bg.safe_sql(EVICT)

        # same OID, same relfilenodes
        node.safe_sql("DROP DATABASE conflict_db")
        node.safe_sql(create_db)

        with node.connect(db="conflict_db") as c:
            c.safe_sql("UPDATE large SET datab = 2")
        bg.safe_sql(EVICT)

        with node.connect(db="conflict_db") as c:
            assert c.safe_sql("SELECT datab, count(*) FROM large GROUP BY 1 ORDER BY 1 LIMIT 10") == [["2", "4000"]]
