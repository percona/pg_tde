import pytest

from pgtde import api

MIXED_ALTER = r"Recursive ALTER TABLE on a mix of encrypted and unencrypted relations is not supported"


@pytest.fixture
def node(tde_node_db):
    tde_node_db.safe_sql("SET default_table_access_method = 'tde_heap'")
    return tde_node_db


def _keeps_encryption(node, rels, sql):
    for r in rels:
        assert api.is_encrypted(node, r) is True, r
    node.safe_sql(sql)
    for r in rels:
        assert api.is_encrypted(node, r) is True, r


def test_new_relfilenode_keeps_encryption(node):
    node.safe_sql("CREATE TABLE t1 (n integer)")
    _keeps_encryption(node, ["t1"], "VACUUM FULL t1")

    node.safe_sql("""
        CREATE TABLE test_tab1 AS SELECT generate_series(1, 10) a;
        CREATE INDEX test_idx1 ON test_tab1 (a);
    """)
    _keeps_encryption(node, ["test_tab1", "test_idx1"], "REINDEX INDEX CONCURRENTLY test_idx1")

    node.safe_sql("""
        CREATE TABLE mvtest_t (id int NOT NULL PRIMARY KEY, type text NOT NULL, amt numeric NOT NULL);
        INSERT INTO mvtest_t VALUES (1, 'x', 2), (2, 'x', 3), (3, 'y', 5), (4, 'y', 7), (5, 'z', 11);
        CREATE MATERIALIZED VIEW mvtest_tm AS
            SELECT type, sum(amt) AS totamt FROM mvtest_t GROUP BY type WITH NO DATA;
    """)
    _keeps_encryption(node, ["mvtest_tm"], "REFRESH MATERIALIZED VIEW mvtest_tm")

    node.safe_sql("""
        CREATE TYPE rewritetype AS (a int);
        CREATE TABLE rewritemetoo1 OF rewritetype;
        CREATE TABLE rewritemetoo2 OF rewritetype;
    """)
    _keeps_encryption(
        node, ["rewritemetoo1", "rewritemetoo2"], "ALTER TYPE rewritetype ALTER ATTRIBUTE a TYPE text CASCADE"
    )

    node.safe_sql("""
        CREATE TABLE encrypted_table (
            id SERIAL, id2 INT, data TEXT, created_at DATE NOT NULL, PRIMARY KEY (id, created_at)
        ) USING tde_heap;
        CREATE INDEX idx_date ON encrypted_table (created_at);
    """)
    _keeps_encryption(node, ["encrypted_table"], "CLUSTER encrypted_table USING idx_date")
    _keeps_encryption(node, ["encrypted_table_id_seq"], "ALTER SEQUENCE encrypted_table_id_seq RESTART")


@pytest.mark.parametrize(
    ("create_owner", "alter_owner", "before", "after"),
    [
        (None, "encrypted_table.id2", False, True),
        ("NONE", "plain_table.id2", False, False),
        ("encrypted_table.id2", "plain_table.id2", True, False),
        ("encrypted_table.id2", "NONE", True, False),
        ("plain_table.id2", "encrypted_table.id2", False, True),
        ("plain_table.id2", "NONE", False, False),
    ],
    ids=["none-enc", "none-plain", "enc-plain", "enc-none", "plain-enc", "plain-none"],
)
def test_seq_owner(node, create_owner, alter_owner, before, after):
    node.safe_sql("""
        CREATE TABLE encrypted_table (id2 INT) USING tde_heap;
        CREATE TABLE plain_table (id2 INT) USING heap;
    """)
    owned = f" OWNED BY {create_owner}" if create_owner else ""
    node.safe_sql(f"CREATE SEQUENCE s{owned}")
    assert api.is_encrypted(node, "s") is before
    node.safe_sql(f"ALTER SEQUENCE s OWNED BY {alter_owner}")
    assert api.is_encrypted(node, "s") is after


def test_mixed_inheritance_rejected(node):
    node.safe_sql("""
        CREATE TABLE cities (name varchar(8), population real, elevation int) USING tde_heap;
        CREATE TABLE state_capitals (state char(2) UNIQUE NOT NULL) INHERITS (cities) USING heap;
        CREATE TABLE capitals (country char(2) UNIQUE NOT NULL) INHERITS (cities) USING tde_heap;
    """)
    node.expect_error(MIXED_ALTER, "ALTER TABLE cities ALTER COLUMN name TYPE TEXT")


def test_mixed_typed_tables_rejected(node):
    node.safe_sql("""
        CREATE TYPE people_type AS (age int, name varchar(8), dob date);
        CREATE TABLE sales_staff OF people_type USING tde_heap;
        CREATE TABLE other_staff OF people_type USING heap;
    """)
    alter = "ALTER TYPE people_type ALTER ATTRIBUTE name TYPE text CASCADE"
    node.expect_error(MIXED_ALTER, alter)

    node.safe_sql("ALTER TABLE other_staff SET ACCESS METHOD tde_heap")
    node.safe_sql(alter)
    for t in ("sales_staff", "other_staff"):
        toast = node.sql_value(f"SELECT pg_tde_is_encrypted('pg_toast.pg_toast_' || '{t}'::regclass::oid)")
        assert toast == "t", t
