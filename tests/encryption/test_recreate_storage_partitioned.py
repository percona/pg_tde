import pytest

from encryption.test_recreate_storage import (
    CANARY,
    assert_rows_after_restart,
    both_access_methods,
    fill,
    rows,
    toast,
)
from pgtde.checks import assert_encrypted_on_disk, assert_plain_on_disk

# Partitioned tables have no storage, the statements recurse to the leaves.
LEAVES = ["p_1", "p_2"]


def make_partitioned(node, am, leaf_am=None):
    """p, range partitioned on id, leaves p_1 (1-10) and p_2 (11-20) using am, or leaf_am[leaf]."""
    node.execute("CREATE TABLE p (id int PRIMARY KEY, n int, label text, body text) PARTITION BY RANGE (id)")
    node.execute("ALTER TABLE p ALTER COLUMN body SET STORAGE EXTERNAL")
    node.execute("CREATE INDEX p_label_idx ON p (label)")
    create_leaves(node, am, leaf_am)
    fill(node, "p")


def create_leaves(node, am, leaf_am=None):
    for i, leaf in enumerate(LEAVES):
        using = (leaf_am or {}).get(leaf, am)
        first = i * 10 + 1
        node.execute(f"CREATE TABLE {leaf} PARTITION OF p FOR VALUES FROM ({first}) TO ({first + 10}) USING {using}")


def tree_rows(node, leaves=LEAVES):
    """Rows of p and of each leaf."""
    return {rel: rows(node, rel) for rel in ["p", *leaves]}


PARTITIONED_REWRITES = [
    ("vacuum_full", "VACUUM FULL p"),
    ("cluster", "CLUSTER p USING p_label_idx"),
    ("alter_column_type", "ALTER TABLE p ALTER COLUMN n TYPE bigint"),
]


@both_access_methods
@pytest.mark.parametrize("statement", [pytest.param(s, id=i) for i, s in PARTITIONED_REWRITES])
def test_partitioned_rewrite_keeps_encryption_state(tde_node_with_key, statement, am, assert_on_disk):
    node = tde_node_with_key
    make_partitioned(node, am)
    before = tree_rows(node)
    old_storage = {leaf: node.relfilenode(leaf) for leaf in LEAVES}
    assert_on_disk(node, "p", CANARY)

    node.execute(statement)

    for leaf in LEAVES:
        assert node.relfilenode(leaf) != old_storage[leaf], f"statement did not recreate the storage of {leaf}"
    assert_on_disk(node, "p", CANARY)
    for leaf in LEAVES:
        assert_on_disk(node, toast(node, leaf), CANARY)
    assert_rows_after_restart(node, before, by_label=LEAVES)


# the ALTER rewrites every leaf and creates their toast tables
@both_access_methods
def test_partitioned_alter_column_type_creating_toast_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    node.execute("CREATE TABLE p (id int PRIMARY KEY, n int, label varchar(40)) PARTITION BY RANGE (id)")
    node.execute("CREATE INDEX p_label_idx ON p (label)")
    create_leaves(node, am)
    node.execute(f"INSERT INTO p SELECT i, i, '{CANARY}-' || i FROM generate_series(1, 20) i")
    old_storage = {leaf: node.relfilenode(leaf) for leaf in LEAVES}
    assert [toast(node, leaf) for leaf in LEAVES] == [None, None]

    node.execute("ALTER TABLE p ALTER COLUMN n TYPE text")

    for leaf in LEAVES:
        assert node.relfilenode(leaf) != old_storage[leaf], f"statement did not recreate the storage of {leaf}"
        assert toast(node, leaf) is not None, f"statement did not create a toast table for {leaf}"
    node.execute("ALTER TABLE p ALTER COLUMN n SET STORAGE EXTERNAL")
    node.execute(f"UPDATE p SET n = repeat('{CANARY}', 200)")
    before = tree_rows(node)
    assert_rows_after_restart(node, before, by_label=LEAVES)
    assert_on_disk(node, "p", CANARY)
    for leaf in LEAVES:
        assert_on_disk(node, toast(node, leaf), CANARY)


# SET ACCESS METHOD on a partitioned table only sets the access method for partitions
# created later, it rewrites nothing (same on PG17 and PG18)
@pytest.mark.parametrize(
    "am, new_am",
    [("tde_heap", "heap"), ("heap", "tde_heap")],
    ids=["tde_heap_to_heap", "heap_to_tde_heap"],
)
def test_partitioned_set_access_method_applies_to_new_partitions(tde_node_with_key, am, new_am):
    node = tde_node_with_key
    on_disk = {"tde_heap": assert_encrypted_on_disk, "heap": assert_plain_on_disk}
    make_partitioned(node, am)
    old_storage = {leaf: node.relfilenode(leaf) for leaf in LEAVES}

    node.execute(f"ALTER TABLE p SET ACCESS METHOD {new_am}")

    assert {leaf: node.relfilenode(leaf) for leaf in LEAVES} == old_storage, "a leaf was rewritten"
    on_disk[am](node, "p", CANARY)
    node.execute("CREATE TABLE p_3 PARTITION OF p FOR VALUES FROM (21) TO (31)")
    fill(node, "p", 21, 30)
    assert node.scalar("SELECT amname FROM pg_class JOIN pg_am ON pg_am.oid = relam WHERE relname = 'p_3'") == new_am
    for leaf in LEAVES:
        on_disk[am](node, leaf, CANARY)
    on_disk[new_am](node, "p_3", CANARY)
    assert_rows_after_restart(node, tree_rows(node, [*LEAVES, "p_3"]), by_label=[*LEAVES, "p_3"])


def test_partitioned_mixed_tree_rewrite_keeps_encryption_state(tde_node_with_key):
    node = tde_node_with_key
    make_partitioned(node, "tde_heap", leaf_am={"p_2": "heap"})
    before = tree_rows(node)
    old_storage = {leaf: node.relfilenode(leaf) for leaf in LEAVES}
    for check, differs, agrees in [(assert_encrypted_on_disk, "p_2", "p_1"), (assert_plain_on_disk, "p_1", "p_2")]:
        with pytest.raises(AssertionError, match=f"leaf partitions of p that differ:\n{differs}: ") as e:
            check(node, "p", CANARY)
        assert f"{agrees}:" not in str(e.value)

    node.execute("VACUUM FULL p")

    for leaf in LEAVES:
        assert node.relfilenode(leaf) != old_storage[leaf], f"statement did not recreate the storage of {leaf}"
    assert_encrypted_on_disk(node, "p_1", CANARY)
    assert_encrypted_on_disk(node, toast(node, "p_1"), CANARY)
    assert_plain_on_disk(node, "p_2", CANARY)
    assert_plain_on_disk(node, toast(node, "p_2"), CANARY)
    assert_rows_after_restart(node, before, by_label=LEAVES)
