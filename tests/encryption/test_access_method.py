import pytest

from pgtde import api

ENFORCE = r"pg_tde\.enforce_encryption is ON, only the tde_heap access method is allowed\."
COLS = "(country_id serial primary key, country_name text unique not null, continent text not null)"
RELS = ["country_table", "country_table_country_id_seq", "country_table_pkey"]


def _status(node):
    return [api.is_encrypted(node, r) for r in RELS]


def _insert(node, *values):
    node.safe_sql(
        "INSERT INTO country_table (country_name, continent) VALUES " + ", ".join(f"('{n}', '{c}')" for n, c in values)
    )


def test_change_access_method(tde_node_db, pg_major):
    node = tde_node_db
    node.safe_sql("""
        CREATE TABLE country_table (
            country_id serial primary key,
            country_name varchar(32) unique not null,
            continent varchar(32) not null
        ) USING tde_heap
    """)
    _insert(node, ("Japan", "Asia"), ("UK", "Europe"), ("USA", "North America"))
    assert _status(node) == [True] * 3

    node.safe_sql("ALTER TABLE country_table SET ACCESS METHOD heap")
    _insert(node, ("France", "Europe"), ("Germany", "Europe"), ("Canada", "NA"))
    assert node.sql_value("SELECT count(*) FROM country_table") == "6"
    assert _status(node) == [False] * 3

    node.safe_sql("ALTER TABLE country_table SET ACCESS METHOD tde_heap")
    _insert(node, ("China", "Asia"), ("Brazil", "SA"), ("Australia", "Oceania"))
    assert node.safe_sql("SELECT country_id FROM country_table ORDER BY 1") == [[str(i)] for i in range(1, 10)]
    assert _status(node) == [True] * 3

    node.safe_sql("SET default_table_access_method = 'heap'")
    if pg_major >= 17:
        node.safe_sql("ALTER TABLE country_table SET ACCESS METHOD DEFAULT")
        assert api.is_encrypted(node, "country_table") is False
        node.safe_sql("SET default_table_access_method = 'tde_heap'")
        node.safe_sql("ALTER TABLE country_table SET ACCESS METHOD DEFAULT")
        assert api.is_encrypted(node, "country_table") is True
    else:
        # PG16, from change_access_method_1.out
        node.expect_error(r'syntax error at or near "DEFAULT"', "ALTER TABLE country_table SET ACCESS METHOD DEFAULT")
        assert api.is_encrypted(node, "country_table") is True
    node.safe_sql("RESET default_table_access_method")

    node.safe_sql("ALTER TABLE country_table ADD y text")
    toast = node.sql_value("SELECT pg_tde_is_encrypted('pg_toast.pg_toast_' || 'country_table'::regclass::oid)")
    assert toast == "t"

    node.safe_sql(f"CREATE TABLE country_table2 {COLS}")
    node.safe_sql("SET pg_tde.enforce_encryption = on")
    node.expect_error(ENFORCE, f"CREATE TABLE country_table3 {COLS} USING heap")
    node.expect_error(ENFORCE, "ALTER TABLE country_table SET ACCESS METHOD heap")
    node.safe_sql("ALTER TABLE country_table2 SET ACCESS METHOD tde_heap")
    node.safe_sql(f"CREATE TABLE country_table3 {COLS} USING tde_heap")
    node.safe_sql("SET pg_tde.enforce_encryption = off")


MIXED_ALTER = r"Recursive ALTER TABLE on a mix of encrypted and unencrypted relations is not supported"


@pytest.fixture
def tde_default_am_node(tde_node_db):
    tde_node_db.safe_sql("SET default_table_access_method = 'tde_heap'")
    return tde_node_db


def _keeps_encryption(node, rels, sql):
    for r in rels:
        assert api.is_encrypted(node, r) is True, r
    node.safe_sql(sql)
    for r in rels:
        assert api.is_encrypted(node, r) is True, r


def test_new_relfilenode_keeps_encryption(tde_default_am_node):
    node = tde_default_am_node
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
def test_seq_owner(tde_default_am_node, create_owner, alter_owner, before, after):
    node = tde_default_am_node
    node.safe_sql("""
        CREATE TABLE encrypted_table (id2 INT) USING tde_heap;
        CREATE TABLE plain_table (id2 INT) USING heap;
    """)
    owned = f" OWNED BY {create_owner}" if create_owner else ""
    node.safe_sql(f"CREATE SEQUENCE s{owned}")
    assert api.is_encrypted(node, "s") is before
    node.safe_sql(f"ALTER SEQUENCE s OWNED BY {alter_owner}")
    assert api.is_encrypted(node, "s") is after


def test_mixed_inheritance_rejected(tde_default_am_node):
    node = tde_default_am_node
    node.safe_sql("""
        CREATE TABLE cities (name varchar(8), population real, elevation int) USING tde_heap;
        CREATE TABLE state_capitals (state char(2) UNIQUE NOT NULL) INHERITS (cities) USING heap;
        CREATE TABLE capitals (country char(2) UNIQUE NOT NULL) INHERITS (cities) USING tde_heap;
    """)
    node.expect_error(MIXED_ALTER, "ALTER TABLE cities ALTER COLUMN name TYPE TEXT")


def test_mixed_typed_tables_rejected(tde_default_am_node):
    node = tde_default_am_node
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


TABLES = {"test_enc": "tde_heap", "test_norm": "heap", "test_temp_enc": "tde_heap", "test_temp_norm": "heap"}


def test_is_encrypted(tde_node_db, pg_major):
    node = tde_node_db
    for name, am in TABLES.items():
        temp = "TEMP " if "temp" in name else ""
        node.safe_sql(f"CREATE {temp}TABLE {name} (id SERIAL, PRIMARY KEY (id)) USING {am}")
    part_sql = "CREATE TABLE test_part (id SERIAL, PRIMARY KEY (id)) PARTITION BY RANGE (id) USING tde_heap"
    if pg_major >= 17:
        node.safe_sql(part_sql)
    else:
        # PG16, from pg_tde_is_encrypted_1.out
        node.expect_error(r"specifying a table access method is not supported on a partitioned table", part_sql)

    expected = {
        "test_enc": True,
        "test_norm": False,
        "test_temp_enc": True,
        "test_temp_norm": False,
        "test_enc_id_seq": True,
        "test_norm_id_seq": False,
        "test_enc_pkey": True,
        "test_norm_pkey": False,
    }
    if pg_major >= 17:
        # partitioned table and index have no storage, but the sequence does
        expected |= {"test_part": None, "test_part_id_seq": True, "test_part_pkey": None}
    for rel, want in expected.items():
        assert api.is_encrypted(node, rel) is want, rel

    assert node.sql_value("SELECT pg_tde_is_encrypted(NULL)") is None
    assert api.key_info(node)[1:] == ["db-provider", "test-db-key"]
