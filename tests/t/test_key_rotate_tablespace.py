from pgtde import api

ROWS = [["1", "Japan", "Asia"], ["2", "UK", "Europe"], ["3", "USA", "North America"]]


def test_key_rotate_tablespace(tde_node, file_keyring):
    node = tde_node
    node.safe_sql("SET allow_in_place_tablespaces = true")
    node.safe_sql("CREATE TABLESPACE test_tblspace LOCATION ''")
    node.safe_sql("CREATE DATABASE tbc TABLESPACE = test_tblspace")

    with node.connect(db="tbc") as tbc:
        api.create_extension(tbc)
        api.add_provider(tbc, file_keyring, "file-vault")
        api.create_key(tbc, "test-db-key", "file-vault")
        api.set_key(tbc, "test-db-key", "file-vault")
        tbc.safe_sql("""
            CREATE TABLE country_table (
                country_id   serial primary key,
                country_name text unique not null,
                continent    text not null
            ) USING tde_heap;
            INSERT INTO country_table (country_name, continent)
                VALUES ('Japan', 'Asia'), ('UK', 'Europe'), ('USA', 'North America');
        """)
        assert tbc.safe_sql("SELECT * FROM country_table") == ROWS

        api.create_key(tbc, "new-k", "file-vault")
        api.set_key(tbc, "new-k", "file-vault")

    node.restart()

    with node.connect(db="tbc") as tbc:
        assert tbc.safe_sql("SELECT * FROM country_table") == ROWS
        api.drop_extension(tbc, cascade=True)

    node.safe_sql("DROP DATABASE tbc")
    node.safe_sql("DROP TABLESPACE test_tblspace")
