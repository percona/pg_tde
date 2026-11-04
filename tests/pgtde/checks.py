ROWS = [["1", "multitude"], ["2", "multitudinous"]]
INSERT = "INSERT INTO {} (k) VALUES ('multitude'), ('multitudinous')"
COLS = "(id SERIAL, k VARCHAR(32), PRIMARY KEY (id))"


def _read(node, t):
    return node.safe_sql(f"SELECT * FROM {t} ORDER BY id")


def check_tde_heap(node):
    expected = {}

    node.safe_sql(f"CREATE TABLE test_enc1 {COLS} USING tde_heap")
    node.safe_sql(INSERT.format("test_enc1"))
    expected["test_enc1"] = ROWS

    node.safe_sql(f"CREATE TABLE test_enc2 {COLS}")
    node.safe_sql(INSERT.format("test_enc2"))
    node.safe_sql("ALTER TABLE test_enc2 SET ACCESS METHOD tde_heap")
    expected["test_enc2"] = ROWS

    node.safe_sql("SET default_table_access_method = 'tde_heap'")
    node.safe_sql(f"CREATE TABLE test_enc3 {COLS}")
    node.safe_sql(INSERT.format("test_enc3"))
    node.safe_sql("RESET default_table_access_method")
    expected["test_enc3"] = ROWS

    if node.pg_major >= 17:
        node.safe_sql(f"CREATE TABLE test_enc4 {COLS} USING heap")
        node.safe_sql(INSERT.format("test_enc4"))
        node.safe_sql("SET default_table_access_method = 'tde_heap'")
        node.safe_sql("ALTER TABLE test_enc4 SET ACCESS METHOD DEFAULT")
        node.safe_sql("RESET default_table_access_method")
        expected["test_enc4"] = ROWS

    node.safe_sql(f"CREATE TABLE test_enc5 {COLS} USING tde_heap")
    node.safe_sql(INSERT.format("test_enc5"))
    node.safe_sql("CHECKPOINT")
    node.safe_sql("TRUNCATE test_enc5")
    node.safe_sql(INSERT.format("test_enc5"))
    expected["test_enc5"] = [["3", "multitude"], ["4", "multitudinous"]]

    # plain heap, cross check for the on disk asserts
    node.safe_sql(f"CREATE TABLE test_enc6 {COLS} USING heap")
    node.safe_sql(INSERT.format("test_enc6"))
    expected["test_enc6"] = ROWS

    for t, rows in expected.items():
        assert _read(node, t) == rows, t

    node.restart()

    for t, rows in expected.items():
        assert _read(node, t) == rows, t

    for t in expected:
        if t == "test_enc6":
            node.assert_on_disk(t, "multitud")
        else:
            node.assert_not_on_disk(t, "multitud")


def setup_error(fn):
    # strict xfail tests: setup failures must not count as the expected AssertionError
    try:
        return fn()
    except AssertionError as e:
        raise RuntimeError(f"setup failed: {e}") from e
