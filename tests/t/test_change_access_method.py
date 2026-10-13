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
