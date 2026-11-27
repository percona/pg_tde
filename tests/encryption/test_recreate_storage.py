import pytest

from pgtde.checks import (
    assert_encrypted_on_disk,
    assert_plain_on_disk,
    assert_sequence_encrypted_on_disk,
    assert_sequence_plain_on_disk,
)

# DDL that moves a relation to a new relfilenode must keep its encryption state:
# encrypted relations stay encrypted, plain ones stay plain.

CANARY = "plaintext-canary"

both_access_methods = pytest.mark.parametrize(
    "am, assert_on_disk",
    [("tde_heap", assert_encrypted_on_disk), ("heap", assert_plain_on_disk)],
    ids=["tde_heap", "heap"],
)


def fill(node, table, first=1, last=20):
    # body is stored out of line, uncompressed: the canary is in the heap, the label index and the toast
    node.execute(
        f"INSERT INTO {table} SELECT i, i, '{CANARY}-' || i, repeat('{CANARY}', 200) "
        f"FROM generate_series({first}, {last}) i"
    )


def make_table(node, table, am):
    node.execute(f"CREATE TABLE {table} (id int PRIMARY KEY, n int, label text, body text) USING {am}")
    node.execute(f"ALTER TABLE {table} ALTER COLUMN body SET STORAGE EXTERNAL")
    node.execute(f"CREATE INDEX {table}_label_idx ON {table} (label)")
    fill(node, table)


def rows(node, table):
    return node.query(f"SELECT * FROM {table} ORDER BY 1")


def assert_rows_after_restart(node, expected, by_label=()):
    """expected: relation -> rows. After a restart, so the rows come from disk, not from shared
    buffers. The relations in by_label are also read through their label index."""
    node.restart()
    for rel, before in expected.items():
        assert rows(node, rel) == before, f"rows of {rel} changed"
    with node.connect() as conn:
        for setting in ["enable_seqscan", "enable_bitmapscan", "enable_sort"]:
            conn.execute(f"SET {setting} = off")
        for rel in by_label:
            q = f"SELECT * FROM {rel} ORDER BY label"
            plan = "\n".join(r[0] for r in conn.query(f"EXPLAIN {q}"))
            assert f"Index Scan using {rel}_label_idx" in plan, plan
            assert sorted(conn.query(q)) == expected[rel], f"rows of {rel} read through its index changed"


def toast(node, table):
    return node.scalar(
        "SELECT NULLIF(reltoastrelid, 0)::regclass::text FROM pg_class WHERE oid = $1::regclass", (table,)
    )


def fill_toast(node, table, column, first, last):
    node.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET STORAGE EXTERNAL")
    node.execute(
        f"INSERT INTO {table} (id, {column}) SELECT i, repeat('{CANARY}', 200) FROM generate_series({first}, {last}) i"
    )


REWRITES = [
    # id, statement, relation that gets the new storage
    ("vacuum_full", "VACUUM FULL t", "t"),
    ("cluster", "CLUSTER t USING t_label_idx", "t"),
    ("reindex", "REINDEX INDEX t_label_idx", "t_label_idx"),
    ("reindex_concurrently", "REINDEX INDEX CONCURRENTLY t_label_idx", "t_label_idx"),
    ("alter_column_type", "ALTER TABLE t ALTER COLUMN n TYPE bigint", "t"),
]


@both_access_methods
@pytest.mark.parametrize("statement, rewritten", [pytest.param(s, r, id=i) for i, s, r in REWRITES])
def test_rewrite_keeps_encryption_state(tde_node_with_key, statement, rewritten, am, assert_on_disk):
    node = tde_node_with_key
    make_table(node, "t", am)
    before = rows(node, "t")
    old_storage = node.relfilenode(rewritten)
    assert_on_disk(node, "t", CANARY)
    assert_on_disk(node, rewritten, CANARY)
    assert_on_disk(node, toast(node, "t"), CANARY)

    node.execute(statement)

    assert node.relfilenode(rewritten) != old_storage, "statement did not recreate the storage"
    assert_on_disk(node, "t", CANARY)
    assert_on_disk(node, rewritten, CANARY)
    assert_on_disk(node, toast(node, "t"), CANARY)
    assert_rows_after_restart(node, {"t": before}, by_label=["t"])


EMPTY_REWRITES = [
    # id, setup, statement, tables that get new storage
    ("vacuum_full", "CREATE TABLE t (id int) USING {am}", "VACUUM FULL t", ["t"]),
    (
        "cluster",
        "CREATE TABLE t (id int, label text) USING {am}; CREATE INDEX t_label_idx ON t (label)",
        "CLUSTER t USING t_label_idx",
        ["t"],
    ),
    (
        "alter_type_cascade",
        "CREATE TYPE item AS (a int); CREATE TABLE items_1 OF item USING {am}; CREATE TABLE items_2 OF item USING {am}",
        "ALTER TYPE item ALTER ATTRIBUTE a TYPE text CASCADE",
        ["items_1", "items_2"],
    ),
]


# empty storage: only the catalog can tell, there are no bytes to search
@pytest.mark.parametrize("am", ["tde_heap", "heap"])
@pytest.mark.parametrize("setup, statement, tables", [pytest.param(*c[1:], id=c[0]) for c in EMPTY_REWRITES])
def test_rewrite_of_empty_table_keeps_encryption_state(tde_node_with_key, setup, statement, tables, am):
    node = tde_node_with_key
    node.execute(setup.format(am=am))
    old_storage = {t: node.relfilenode(t) for t in tables}

    node.execute(statement)

    for t in tables:
        assert node.relfilenode(t) != old_storage[t], f"statement did not recreate the storage of {t}"
    node.restart()
    for t in tables:
        for r in node.related_relations(t):
            assert node.tde.is_encrypted(r) == (am == "tde_heap"), f"{r} changed its encryption state"
        assert rows(node, t) == []


@both_access_methods
def test_truncate_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    make_table(node, "t", am)
    before = rows(node, "t")
    old_storage = node.relfilenode("t")
    assert_on_disk(node, "t", CANARY)
    assert_on_disk(node, toast(node, "t"), CANARY)

    node.execute("TRUNCATE t")
    fill(node, "t")

    assert node.relfilenode("t") != old_storage, "statement did not recreate the storage"
    assert_on_disk(node, "t", CANARY)
    assert_on_disk(node, toast(node, "t"), CANARY)
    assert_rows_after_restart(node, {"t": before}, by_label=["t"])


@both_access_methods
def test_refresh_matview_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    make_table(node, "t", am)
    node.execute(f"CREATE MATERIALIZED VIEW mv USING {am} AS SELECT id, label FROM t")
    node.execute("CREATE INDEX mv_label_idx ON mv (label)")
    before = rows(node, "mv")
    old_storage = node.relfilenode("mv")
    assert_on_disk(node, "mv", CANARY)

    node.execute("REFRESH MATERIALIZED VIEW mv")

    assert node.relfilenode("mv") != old_storage, "statement did not recreate the storage"
    assert_on_disk(node, "mv", CANARY)
    assert_rows_after_restart(node, {"mv": before}, by_label=["mv"])


@both_access_methods
def test_refresh_unpopulated_matview_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    make_table(node, "t", am)
    node.execute(f"CREATE MATERIALIZED VIEW mv USING {am} AS SELECT id, label FROM t WITH NO DATA")
    node.execute("CREATE INDEX mv_label_idx ON mv (label)")
    old_storage = node.relfilenode("mv")
    # empty storage, the bytes cannot tell
    for r in node.related_relations("mv"):
        assert node.tde.is_encrypted(r) == (am == "tde_heap"), r

    node.execute("REFRESH MATERIALIZED VIEW mv")

    assert node.relfilenode("mv") != old_storage, "statement did not recreate the storage"
    assert_on_disk(node, "mv", CANARY)
    assert_rows_after_restart(node, {"mv": node.query("SELECT id, label FROM t ORDER BY 1")}, by_label=["mv"])


# the ALTER rewrites the table and creates its toast table, which gets the state of the table
@both_access_methods
def test_alter_column_type_creating_toast_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    node.execute(f"CREATE TABLE t (id int PRIMARY KEY, n int, label varchar(40)) USING {am}")
    node.execute("CREATE INDEX t_label_idx ON t (label)")
    node.execute(f"INSERT INTO t SELECT i, i, '{CANARY}-' || i FROM generate_series(1, 20) i")
    before = node.query("SELECT id, n::text, label FROM t ORDER BY 1")
    old_storage = node.relfilenode("t")
    assert toast(node, "t") is None

    node.execute("ALTER TABLE t ALTER COLUMN n TYPE text")

    assert node.relfilenode("t") != old_storage, "statement did not recreate the storage"
    new_toast = toast(node, "t")
    assert new_toast is not None, "statement did not create a toast table"
    assert_rows_after_restart(node, {"t": before}, by_label=["t"])
    fill_toast(node, "t", "n", 21, 40)
    assert_on_disk(node, "t", CANARY)
    assert_on_disk(node, new_toast, CANARY)


@both_access_methods
def test_alter_type_cascade_keeps_encryption_state(tde_node_with_key, am, assert_on_disk):
    node = tde_node_with_key
    node.execute("CREATE TYPE item AS (id int, n int, label varchar(40))")
    tables = ["items_1", "items_2"]
    for t in tables:
        node.execute(f"CREATE TABLE {t} OF item USING {am}")
        node.execute(f"CREATE INDEX {t}_label_idx ON {t} (label)")
        node.execute(f"INSERT INTO {t} SELECT i, i, '{CANARY}-' || i FROM generate_series(1, 20) i")
    before = {t: node.query(f"SELECT id, n::text, label FROM {t} ORDER BY 1") for t in tables}
    old_storage = {t: node.relfilenode(t) for t in tables}
    assert [toast(node, t) for t in tables] == [None, None]

    node.execute("ALTER TYPE item ALTER ATTRIBUTE n TYPE text CASCADE")

    for t in tables:
        assert node.relfilenode(t) != old_storage[t], f"statement did not recreate the storage of {t}"
    assert_rows_after_restart(node, before, by_label=tables)
    for t in tables:
        new_toast = toast(node, t)
        assert new_toast is not None, f"statement did not create a toast table for {t}"
        fill_toast(node, t, "n", 21, 40)
        assert_on_disk(node, t, CANARY)
        assert_on_disk(node, new_toast, CANARY)


# tde_heap from default_table_access_method instead of USING, also for CREATE TABLE AS
def test_default_access_method_keeps_encryption_state(tde_node_with_key):
    node = tde_node_with_key
    node.execute("SET default_table_access_method = tde_heap")
    node.execute("CREATE TABLE t (id int, label text)")
    node.execute(f"INSERT INTO t SELECT i, '{CANARY}-' || i FROM generate_series(1, 20) i")
    node.execute("CREATE TABLE t_copy AS SELECT * FROM t")
    node.execute("CREATE MATERIALIZED VIEW mv AS SELECT * FROM t")
    rewrites = {"t": "VACUUM FULL t", "t_copy": "VACUUM FULL t_copy", "mv": "REFRESH MATERIALIZED VIEW mv"}
    before = {}

    for rel, statement in rewrites.items():
        assert_encrypted_on_disk(node, rel, CANARY)
        before[rel] = rows(node, rel)
        old_storage = node.relfilenode(rel)

        node.execute(statement)

        assert node.relfilenode(rel) != old_storage, f"{statement} did not recreate the storage"
        assert_encrypted_on_disk(node, rel, CANARY)
    assert_rows_after_restart(node, before)


@pytest.mark.parametrize(
    "am, assert_sequence_on_disk",
    [("tde_heap", assert_sequence_encrypted_on_disk), ("heap", assert_sequence_plain_on_disk)],
    ids=["tde_heap", "heap"],
)
def test_sequence_restart_keeps_encryption_state(tde_node_with_key, am, assert_sequence_on_disk):
    node = tde_node_with_key
    node.execute(f"CREATE TABLE t (id serial) USING {am}")
    assert node.scalar("SELECT nextval('t_id_seq')") == 1
    old_storage = node.relfilenode("t_id_seq")
    assert_sequence_on_disk(node, "t_id_seq")

    node.execute("ALTER SEQUENCE t_id_seq RESTART")

    assert node.relfilenode("t_id_seq") != old_storage, "statement did not recreate the storage"
    assert_sequence_on_disk(node, "t_id_seq")
    assert node.scalar("SELECT nextval('t_id_seq')") == 1


OWNER = {"independent": "NONE", "encrypted": "enc.n", "plain": "plain.n"}


# a sequence is encrypted exactly when the table owning it is
@pytest.mark.parametrize(
    "start, target",
    [
        ("independent", "encrypted"),
        ("independent", "plain"),
        ("encrypted", "plain"),
        ("encrypted", "independent"),
        ("plain", "encrypted"),
        ("plain", "independent"),
    ],
)
def test_sequence_follows_owner(tde_node_with_key, start, target):
    node = tde_node_with_key
    node.execute("CREATE TABLE enc (n int) USING tde_heap")
    node.execute("CREATE TABLE plain (n int) USING heap")

    def assert_on_disk(owner):
        if owner == "encrypted":
            assert_sequence_encrypted_on_disk(node, "s")
        else:
            assert_sequence_plain_on_disk(node, "s")

    node.execute(f"CREATE SEQUENCE s OWNED BY {OWNER[start]}")
    assert node.scalar("SELECT nextval('s')") == 1
    assert_on_disk(start)

    node.execute(f"ALTER SEQUENCE s OWNED BY {OWNER[target]}")

    assert_on_disk(target)
    assert node.scalar("SELECT nextval('s')") == 2


def encryption_state(node, tables):
    return {t: (node.tde.is_encrypted(t), node.relfilenode(t), toast(node, t), rows(node, t)) for t in tables}


# one ALTER pass cannot serve encrypted and plain relations at once, e.g. for the toast
# tables it creates (PG-1507, PG-1508)
def test_recursive_alter_on_mixed_inheritance_is_refused(tde_node_with_key):
    node = tde_node_with_key
    node.execute("CREATE TABLE cities (name varchar(20), population int) USING tde_heap")
    node.execute("CREATE TABLE plain_capitals (state char(2)) INHERITS (cities) USING heap")
    node.execute("CREATE TABLE enc_capitals (country char(2)) INHERITS (cities) USING tde_heap")
    tables = ["cities", "plain_capitals", "enc_capitals"]
    for t in tables:
        node.execute(f"INSERT INTO {t} (name, population) VALUES ('{CANARY}', 1)")
    before = encryption_state(node, tables)

    node.expect_error(
        "mix of encrypted and unencrypted relations is not supported",
        "ALTER TABLE cities ALTER COLUMN name TYPE text",
    )

    assert encryption_state(node, tables) == before
    assert_encrypted_on_disk(node, "cities", CANARY)
    assert_encrypted_on_disk(node, "enc_capitals", CANARY)
    assert_plain_on_disk(node, "plain_capitals", CANARY)


def test_alter_type_cascade_on_mixed_typed_tables_is_refused(tde_node_with_key):
    node = tde_node_with_key
    node.execute("CREATE TYPE person AS (id int, name varchar(20))")
    node.execute("CREATE TABLE enc_staff OF person USING tde_heap")
    node.execute("CREATE TABLE plain_staff OF person USING heap")
    tables = ["enc_staff", "plain_staff"]
    for t in tables:
        node.execute(f"INSERT INTO {t} VALUES (1, '{CANARY}')")
    before = encryption_state(node, tables)

    node.expect_error(
        "mix of encrypted and unencrypted relations is not supported",
        "ALTER TYPE person ALTER ATTRIBUTE name TYPE text CASCADE",
    )

    assert encryption_state(node, tables) == before
    assert_encrypted_on_disk(node, "enc_staff", CANARY)
    assert_plain_on_disk(node, "plain_staff", CANARY)

    # with every typed table encrypted the same statement works, the new toast tables are encrypted
    node.execute("ALTER TABLE plain_staff SET ACCESS METHOD tde_heap")
    node.execute("ALTER TYPE person ALTER ATTRIBUTE name TYPE text CASCADE")
    for t in tables:
        new_toast = toast(node, t)
        assert new_toast is not None, f"statement did not create a toast table for {t}"
        fill_toast(node, t, "name", 2, 10)
        assert_encrypted_on_disk(node, t, CANARY)
        assert_encrypted_on_disk(node, new_toast, CANARY)
        assert node.query(f"SELECT id, name FROM {t} WHERE id = 1") == [(1, CANARY)]
