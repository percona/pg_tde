from pgtde import api

TABLES = {"test_enc": "tde_heap", "test_norm": "heap", "test_temp_enc": "tde_heap", "test_temp_norm": "heap"}


def test_pg_tde_is_encrypted(tde_node_db, pg_major):
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
    assert api.key_info(node)[1:] == ["file-vault", "test-db-key"]
