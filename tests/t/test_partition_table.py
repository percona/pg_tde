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
