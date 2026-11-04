from pgtde import api

ROWS = [["1", "5"], ["2", "6"]]
PROVIDER_TYPE = {"file": "file", "vault": "vault-v2", "kmip": "kmip"}


BLOB_LEN = 9000


def _create_tables(node):
    node.safe_sql("""
        CREATE TABLE test_enc (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap;
        INSERT INTO test_enc (k) VALUES (5), (6);
    """)
    node.safe_sql("""
        CREATE TABLE parts (id int, p int) PARTITION BY RANGE (p);
        CREATE TABLE parts_1 PARTITION OF parts FOR VALUES FROM (0) TO (50) USING tde_heap;
        CREATE TABLE parts_2 PARTITION OF parts FOR VALUES FROM (50) TO (100) USING tde_heap;
        INSERT INTO parts SELECT i, i % 100 FROM generate_series(1, 120) i;
    """)
    node.safe_sql(f"""
        CREATE TABLE wide (id int PRIMARY KEY, blob text) USING tde_heap;
        ALTER TABLE wide ALTER COLUMN blob SET STORAGE EXTERNAL;
        INSERT INTO wide VALUES (1, repeat('Z', {BLOB_LEN}));
    """)


def _read(node, tables):
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == ROWS
    for i, t in enumerate(tables):
        assert node.safe_sql(f"SELECT x FROM {t}") == [[str(i)]], t
    for part, n in (("parts_1", "70"), ("parts_2", "50")):
        assert api.is_encrypted(node, part) is True, part
        assert node.sql_value(f"SELECT count(*) FROM {part}") == n, part
    toast = node.sql_value("SELECT reltoastrelid::regclass FROM pg_class WHERE oid = 'wide'::regclass")
    assert toast is not None and toast != "-"
    assert api.is_encrypted(node, toast) is True
    assert node.sql_value(f"SELECT count(*) FROM {toast}") != "0"
    assert node.sql_value("SELECT length(blob) FROM wide WHERE id = 1") == str(BLOB_LEN)


def _rotate(node, key, provider, scope, info, tables):
    api.create_key(node, key, provider, scope=scope)
    api.set_key(node, key, provider, scope=scope)
    api.verify_key(node)
    # new relation key under the new principal key
    t = f"t_{len(tables)}"
    node.safe_sql(f"CREATE TABLE {t} (x int) USING tde_heap")
    node.safe_sql(f"INSERT INTO {t} VALUES ({len(tables)})")
    tables.append(t)
    _read(node, tables)
    node.restart()
    api.verify_key(node)
    assert api.key_info(node) == info
    assert api.server_key_info(node) is None
    _read(node, tables)


def test_rotate_key_across_providers_and_scopes(tde_node, keyring_obj, tmp_path):
    node = tde_node
    db2 = tmp_path / "db2.keys"
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "db-provider")
    api.add_provider(node, db2, "file-2")
    api.add_provider(node, keyring_obj, "global-provider", scope="global")
    api.add_provider(node, tmp_path / "global3.keys", "file-3", scope="global")

    listing = api.list_providers(node)
    assert [r[1] for r in listing] == ["db-provider", "file-2"]
    assert listing[0][:3] == ["1", "db-provider", PROVIDER_TYPE[keyring_obj.kind]]
    assert listing[1] == ["2", "file-2", "file", f'{{"path" : "{db2}"}}']

    api.create_key(node, "test-db-key", "db-provider")
    api.set_key(node, "test-db-key", "db-provider")
    _create_tables(node)
    tables = []
    _read(node, tables)

    _rotate(node, "rotated-key1", "db-provider", "database", ["1", "db-provider", "rotated-key1"], tables)
    _rotate(node, "rotated-key2", "file-2", "database", ["2", "file-2", "rotated-key2"], tables)
    _rotate(node, "rotated-key", "file-3", "global", ["-2", "file-3", "rotated-key"], tables)
    _rotate(node, "rotated-keyX", "global-provider", "global", ["-1", "global-provider", "rotated-keyX"], tables)
    api.delete_provider(node, "file-3", scope="global")
    assert [r[1] for r in api.list_providers(node, scope="global")] == ["global-provider"]

    node.safe_sql("ALTER SYSTEM SET pg_tde.inherit_global_providers = off")
    node.restart()

    disabled = r"usage of global key providers is disabled"
    node.expect_error(
        disabled, "SELECT pg_tde_create_key_using_global_key_provider('rotated-keyX2', 'global-provider')"
    )
    node.expect_error(disabled, "SELECT pg_tde_set_key_using_global_key_provider('rotated-keyX2', 'global-provider')")
    assert api.key_info(node) == ["-1", "global-provider", "rotated-keyX"]
    assert api.server_key_info(node) is None

    # global key to database key
    api.set_key(node, "rotated-key2", "file-2")
    assert api.key_info(node) == ["2", "file-2", "rotated-key2"]
    assert api.server_key_info(node) is None
    node.safe_sql("CREATE TABLE inherit_off (x int) USING tde_heap")
    assert api.is_encrypted(node, "inherit_off") is True
    node.restart()
    assert api.key_info(node) == ["2", "file-2", "rotated-key2"]
    _read(node, tables)

    node.safe_sql("DROP TABLE test_enc")
    node.safe_sql("ALTER SYSTEM RESET pg_tde.inherit_global_providers")
    node.restart()
    api.drop_extension(node, cascade=True)


COUNTRY_ROWS = [["1", "Japan", "Asia"], ["2", "UK", "Europe"], ["3", "USA", "North America"]]


def test_rotate_key_tablespace(tde_node, keyring_obj):
    node = tde_node
    node.safe_sql("SET allow_in_place_tablespaces = true")
    node.safe_sql("CREATE TABLESPACE test_tblspace LOCATION ''")
    node.safe_sql("CREATE DATABASE tbc TABLESPACE = test_tblspace")

    with node.connect(db="tbc") as tbc:
        api.create_extension(tbc)
        api.add_provider(tbc, keyring_obj, "db-provider")
        api.create_key(tbc, "test-db-key", "db-provider")
        api.set_key(tbc, "test-db-key", "db-provider")
        tbc.safe_sql("""
            CREATE TABLE country_table (
                country_id   serial primary key,
                country_name text unique not null,
                continent    text not null
            ) USING tde_heap;
            INSERT INTO country_table (country_name, continent)
                VALUES ('Japan', 'Asia'), ('UK', 'Europe'), ('USA', 'North America');
        """)
        assert tbc.safe_sql("SELECT * FROM country_table") == COUNTRY_ROWS

        api.create_key(tbc, "new-k", "db-provider")
        api.set_key(tbc, "new-k", "db-provider")

    node.restart()

    with node.connect(db="tbc") as tbc:
        assert tbc.safe_sql("SELECT * FROM country_table") == COUNTRY_ROWS
        api.drop_extension(tbc, cascade=True)

    node.safe_sql("DROP DATABASE tbc")
    node.safe_sql("DROP TABLESPACE test_tblspace")
