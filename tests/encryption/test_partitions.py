import pytest

from pgtde import api

ENFORCE = r"pg_tde\.enforce_encryption is ON, only the tde_heap access method is allowed\."
MIXED_ALTER = r"Recursive ALTER TABLE on a mix of encrypted and unencrypted relations is not supported"
MIXED_INDEX = r"Recursive CREATE INDEX on a mix of encrypted and unencrypted relations is not supported"
NO_PARENT_AM = r"specifying a table access method is not supported on a partitioned table"

QUARTERS = {
    "partition_q1_2024": ("2024-01-01", "2024-04-01"),
    "partition_q2_2024": ("2024-04-01", "2024-07-01"),
    "partition_q3_2024": ("2024-07-01", "2024-10-01"),
    "partition_q4_2024": ("2024-10-01", "2025-01-01"),
}


@pytest.fixture
def node(tde_node_db):
    return tde_node_db


def _parent(node, sql, pg_major):
    # a partitioned table with an AM; PG16 rejects it (partition_table_1.out)
    if pg_major >= 17:
        node.safe_sql(sql)
        return True
    node.expect_error(NO_PARENT_AM, sql)
    return False


def _children(node):
    return [api.is_encrypted(node, q) for q in QUARTERS]


def test_mixed_children(node, pg_major):
    if not _parent(
        node,
        """
        CREATE TABLE partitioned_table (
            id SERIAL, data TEXT, created_at DATE NOT NULL, PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at) USING tde_heap
        """,
        pg_major,
    ):
        return
    for i, (q, (lo, hi)) in enumerate(QUARTERS.items()):
        am = "heap" if i % 2 else "tde_heap"
        node.safe_sql(
            f"CREATE TABLE {q} PARTITION OF partitioned_table FOR VALUES FROM ('{lo}') TO ('{hi}') USING {am}"
        )
    assert api.is_encrypted(node, "partitioned_table") is None
    assert _children(node) == [True, False, True, False]

    node.expect_error(MIXED_ALTER, "ALTER TABLE partitioned_table SET ACCESS METHOD heap")

    for i, q in enumerate(QUARTERS):
        am = "tde_heap" if i % 2 else "heap"
        node.safe_sql(f"ALTER TABLE {q} SET ACCESS METHOD {am}")
    assert api.is_encrypted(node, "partitioned_table") is None
    assert _children(node) == [False, True, False, True]

    # parent AM does not matter as long as all children with storage agree
    for q in QUARTERS:
        node.safe_sql(f"ALTER TABLE {q} SET ACCESS METHOD tde_heap")
    node.safe_sql("ALTER TABLE partitioned_table SET ACCESS METHOD heap")
    assert _children(node) == [True] * 4


@pytest.mark.parametrize(("default_am", "parent_am", "want"), [("heap", "tde_heap", True), ("tde_heap", "heap", False)])
def test_child_inherits_parent_am(node, pg_major, default_am, parent_am, want):
    node.safe_sql(f"SET default_table_access_method = '{default_am}'")
    if not _parent(node, f"CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a) USING {parent_am}", pg_major):
        return
    node.safe_sql("CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9)")
    assert api.is_encrypted(node, "partition_child") is want


def test_child_uses_default_am(node):
    node.safe_sql("""
        CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
        SET default_table_access_method = 'tde_heap';
        CREATE TABLE partition_child_tde PARTITION OF partition_parent FOR VALUES FROM (0) TO (9);
        SET default_table_access_method = 'heap';
        CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (10) TO (19);
    """)
    assert api.is_encrypted(node, "partition_child_tde") is True
    assert api.is_encrypted(node, "partition_child_heap") is False


def test_enforce_encryption_with_plain_parent(node, pg_major):
    if not _parent(node, "CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a) USING heap", pg_major):
        return
    node.safe_sql("SET pg_tde.enforce_encryption = on")
    node.expect_error(
        ENFORCE, "CREATE TABLE partition_child_inherit PARTITION OF partition_parent FOR VALUES FROM (0) TO (10)"
    )
    node.expect_error(
        ENFORCE,
        "CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (11) TO (20) USING heap",
    )
    node.safe_sql("""
        CREATE TABLE partition_child_tde_heap PARTITION OF partition_parent
            FOR VALUES FROM (11) TO (20) USING tde_heap
    """)
    assert api.is_encrypted(node, "partition_child_tde_heap") is True
    node.safe_sql("RESET pg_tde.enforce_encryption")


def test_rewrite_keeps_child_encryption(node, pg_major):
    if not _parent(
        node, "CREATE TABLE partition_parent (a int, b int) PARTITION BY RANGE (a) USING tde_heap", pg_major
    ):
        return
    node.safe_sql(
        "CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING tde_heap"
    )
    assert api.is_encrypted(node, "partition_child") is True
    node.safe_sql("ALTER TABLE partition_parent SET ACCESS METHOD heap, ALTER b TYPE bigint")
    assert node.safe_sql("""
        SELECT relname, amname FROM pg_class JOIN pg_am ON pg_am.oid = relam
        WHERE relname IN ('partition_parent', 'partition_child') ORDER BY 1
    """) == [["partition_child", "tde_heap"], ["partition_parent", "heap"]]
    assert api.is_encrypted(node, "partition_child") is True


@pytest.mark.parametrize(("am", "want"), [("tde_heap", True), ("heap", False)])
def test_partitioned_index(node, am, want):
    node.safe_sql(f"""
        CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
        CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING {am};
        CREATE INDEX ON partition_parent (a);
    """)
    assert api.is_encrypted(node, "partition_parent_a_idx") is None
    assert api.is_encrypted(node, "partition_child_a_idx") is want


def test_partitioned_index_mixed(node):
    node.safe_sql("""
        CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
        CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING heap;
        CREATE TABLE partition_child_tde_heap PARTITION OF partition_parent FOR VALUES FROM (10) TO (19) USING tde_heap;
    """)
    node.expect_error(MIXED_INDEX, "CREATE INDEX ON partition_parent (a)")


def test_partitioned_index_new_partition(node):
    node.safe_sql("""
        CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
        CREATE INDEX ON partition_parent (a);
        CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (10) TO (19) USING tde_heap;
    """)
    assert api.is_encrypted(node, "partition_child_a_idx") is True


TREE = """
    SET default_table_access_method = 'tde_heap';
    CREATE TABLE sales (yr int, mo int, region text, id int, note text, PRIMARY KEY (yr, mo, region, id))
        PARTITION BY RANGE (yr, mo);
    CREATE TABLE sales_2024 PARTITION OF sales FOR VALUES FROM (2024, 1) TO (2025, 1);
    CREATE TABLE sales_2025 PARTITION OF sales FOR VALUES FROM (2025, 1) TO (2026, 1) PARTITION BY LIST (region);
    CREATE TABLE sales_2025_na PARTITION OF sales_2025 FOR VALUES IN ('na');
    CREATE TABLE sales_2025_other PARTITION OF sales_2025 DEFAULT;
    CREATE TABLE sales_2026 PARTITION OF sales FOR VALUES FROM (2026, 1) TO (2027, 1) PARTITION BY HASH (id);
    CREATE TABLE sales_2026_h0 PARTITION OF sales_2026 FOR VALUES WITH (MODULUS 2, REMAINDER 0);
    CREATE TABLE sales_2026_h1 PARTITION OF sales_2026 FOR VALUES WITH (MODULUS 2, REMAINDER 1);
    CREATE TABLE sales_default PARTITION OF sales DEFAULT;
    RESET default_table_access_method;
    ALTER TABLE sales_2024 ALTER COLUMN note SET STORAGE EXTERNAL;
    INSERT INTO sales
        SELECT 2024 + i % 4, 1 + i % 12, (ARRAY['na', 'emea', 'apac'])[1 + i % 3], i, 'secret-' || i
        FROM generate_series(1, 1200) i;
    INSERT INTO sales VALUES (2024, 6, 'na', 100000, repeat('toasted-secret', 2000));
"""

LEAVES = {
    "sales_2024": "yr = 2024",
    "sales_2025_na": "yr = 2025 AND region = 'na'",
    "sales_2025_other": "yr = 2025 AND region <> 'na'",
    "sales_2026_h0": None,
    "sales_2026_h1": None,
    "sales_default": "yr = 2027",
}


def _leaf_counts(node):
    return {leaf: node.sql_value(f"SELECT count(*) FROM {leaf}") for leaf in LEAVES}


def _check_tree(node, counts):
    for rel in ("sales", "sales_2025", "sales_2026", "sales_pkey", "sales_2025_pkey", "sales_2026_pkey"):
        assert api.is_encrypted(node, rel) is None, rel
    for leaf in LEAVES:
        assert api.is_encrypted(node, leaf) is True, leaf
        assert api.is_encrypted(node, f"{leaf}_pkey") is True, leaf
    assert _leaf_counts(node) == counts
    assert node.sql_value("SELECT length(note) FROM sales WHERE id = 100000") == str(len("toasted-secret") * 2000)


def test_partition_tree_leaves_encrypted(node):
    node.safe_sql(TREE)
    counts = _leaf_counts(node)
    for leaf, cond in LEAVES.items():
        assert int(counts[leaf]) > 0, leaf
        if cond:
            want = node.sql_value(f"SELECT count(*) FROM sales WHERE {cond}")
            assert counts[leaf] == want, leaf
    assert int(counts["sales_2026_h0"]) + int(counts["sales_2026_h1"]) == 300
    toast = node.sql_value("SELECT reltoastrelid::regclass::text FROM pg_class WHERE relname = 'sales_2024'")
    assert api.is_encrypted(node, toast) is True
    _check_tree(node, counts)

    node.restart()

    _check_tree(node, counts)
    for leaf in LEAVES:
        node.assert_not_on_disk(leaf, "secret-")
    node.assert_not_on_disk(toast, "toasted-secret")


def test_attach_detach_keeps_encryption(node):
    node.safe_sql("""
        CREATE TABLE standalone (id int PRIMARY KEY, payload text) USING tde_heap;
        INSERT INTO standalone SELECT i, md5(i::text) FROM generate_series(1, 50) i;
        CREATE TABLE attach_parent (id int PRIMARY KEY, payload text) PARTITION BY RANGE (id);
        ALTER TABLE attach_parent ATTACH PARTITION standalone FOR VALUES FROM (1) TO (100);
        INSERT INTO attach_parent VALUES (60, 'via-parent');
    """)
    for rel in ("standalone", "standalone_pkey"):
        assert api.is_encrypted(node, rel) is True, rel
    assert node.sql_value("SELECT count(*) FROM attach_parent") == "51"

    node.safe_sql("ALTER TABLE attach_parent DETACH PARTITION standalone")
    for rel in ("standalone", "standalone_pkey"):
        assert api.is_encrypted(node, rel) is True, rel
    assert node.sql_value("SELECT payload FROM standalone WHERE id = 60") == "via-parent"
    assert node.sql_value("SELECT count(*) FROM attach_parent") == "0"


RW_LEAVES = ("rw_low", "rw_high")


def _rw_filenodes(node):
    return {leaf: node.sql_value(f"SELECT pg_relation_filenode('{leaf}')") for leaf in RW_LEAVES}


def _rw_check(node, low, high):
    for leaf in RW_LEAVES:
        assert api.is_encrypted(node, leaf) is True, leaf
    assert [node.sql_value(f"SELECT count(*) FROM {leaf}") for leaf in RW_LEAVES] == [str(low), str(high)]


def test_partition_rewrites_keep_encryption(node, tmp_path):
    node.safe_sql("""
        CREATE TABLE rw (id int, val int, payload text) PARTITION BY RANGE (id);
        CREATE TABLE rw_low PARTITION OF rw FOR VALUES FROM (0) TO (500) USING tde_heap;
        CREATE TABLE rw_high PARTITION OF rw FOR VALUES FROM (500) TO (1000) USING tde_heap;
        INSERT INTO rw SELECT i, i * 7, 'secret-' || i FROM generate_series(0, 999) i;
        DELETE FROM rw WHERE id % 2 = 0;
    """)
    _rw_check(node, 250, 250)

    before = _rw_filenodes(node)
    node.safe_sql("VACUUM FULL rw_low")
    assert _rw_filenodes(node)["rw_low"] != before["rw_low"]
    _rw_check(node, 250, 250)

    before = _rw_filenodes(node)
    node.safe_sql("ALTER TABLE rw ALTER COLUMN val TYPE bigint USING val::bigint")
    after = _rw_filenodes(node)
    assert all(after[leaf] != before[leaf] for leaf in RW_LEAVES)
    _rw_check(node, 250, 250)
    assert node.sql_value("SELECT sum(val) FROM rw") == str(sum(i * 7 for i in range(1, 1000, 2)))

    # row movement: ids 1..99 move to rw_high
    node.safe_sql("UPDATE rw SET id = id + 501 WHERE id < 100")
    _rw_check(node, 200, 300)
    assert node.sql_value("SELECT payload FROM rw_high WHERE id = 502") == "secret-1"

    before = _rw_filenodes(node)
    node.safe_sql("TRUNCATE rw")
    after = _rw_filenodes(node)
    assert all(after[leaf] != before[leaf] for leaf in RW_LEAVES)
    _rw_check(node, 0, 0)

    csv = tmp_path / "rw.csv"
    csv.write_text("".join(f"{i},{i},secret-{i}\n" for i in range(1000)))
    node.safe_sql(f"COPY rw FROM '{csv}' WITH (FORMAT csv)")
    _rw_check(node, 500, 500)

    node.safe_sql("CHECKPOINT")
    for leaf in RW_LEAVES:
        node.assert_not_on_disk(leaf, "secret-")
