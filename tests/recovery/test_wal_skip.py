import re

import pytest
from stormweaver import SqlError

from pgtde import api
from pgtde.sql import sql_literal

# wal_level=minimal skips WAL for relations created in the same transaction,
# from upstream src/test/recovery/t/018_wal_optimize.pl
pytestmark = pytest.mark.node_config(
    {
        "wal_level": "minimal",
        "max_wal_senders": "0",
        "archive_mode": "off",
        "wal_skip_threshold": "0",
        "max_prepared_transactions": "1",
        "wal_log_hints": "on",
    }
)

PG_1805 = (
    "TODO: PG-1805 only partly fixed -- redo of INSTALL_EXTENSION runs "
    "principal_key_startup_cleanup and drops relation keys created later "
    "(unlogged init forks / WAL-skipped tables); may need its own ticket"
)
COPY_ROWS = [["20000", "30000"], ["20001", "30001"], ["20002", "30002"]]
IN_PG_DEFAULT = ("SELECT reltablespace FROM pg_class WHERE relname = 't'", [["0"]])
TRUNC_COPY = """
    BEGIN;
    CREATE TABLE t (id serial PRIMARY KEY, id2 int) USING tde_heap;
    INSERT INTO t VALUES (DEFAULT, generate_series(1, 3000));
    TRUNCATE t;
    {savepoints}
    COPY t FROM {copy} DELIMITER ',';
    COMMIT;
"""
INS_TRIGGERS = """
    BEGIN;
    CREATE TABLE t (id serial PRIMARY KEY, id2 text) USING tde_heap;
    CREATE FUNCTION t_before() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.id2 NOT LIKE 'triggered%' THEN
            INSERT INTO t VALUES (DEFAULT, 'triggered row before' || NEW.id2);
        END IF;
        RETURN NEW;
    END; $$;
    CREATE FUNCTION t_after() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.id2 NOT LIKE 'triggered%' THEN
            INSERT INTO t VALUES (DEFAULT, 'triggered row after' || NEW.id2);
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER t_before BEFORE INSERT ON t FOR EACH ROW EXECUTE PROCEDURE t_before();
    CREATE TRIGGER t_after AFTER INSERT ON t FOR EACH ROW EXECUTE PROCEDURE t_after();
    COPY t FROM {copy} DELIMITER ',';
    COMMIT;
"""
TRUNC_TRIGGERS = """
    BEGIN;
    CREATE TABLE t (id serial PRIMARY KEY, id2 text) USING tde_heap;
    CREATE FUNCTION t_before() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN INSERT INTO t VALUES (DEFAULT, 'triggered stat before'); RETURN NULL; END; $$;
    CREATE FUNCTION t_after() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN INSERT INTO t VALUES (DEFAULT, 'triggered stat after'); RETURN NULL; END; $$;
    CREATE TRIGGER t_before BEFORE TRUNCATE ON t FOR EACH STATEMENT EXECUTE PROCEDURE t_before();
    CREATE TRIGGER t_after AFTER TRUNCATE ON t FOR EACH STATEMENT EXECUTE PROCEDURE t_after();
    INSERT INTO t VALUES (DEFAULT, 1);
    TRUNCATE t;
    COPY t FROM {copy} DELIMITER ',';
    COMMIT;
"""
TRUNC_INSERT = """
    CREATE TABLE t (id serial PRIMARY KEY) USING tde_heap;
    INSERT INTO t VALUES (DEFAULT);
    TRUNCATE t;
    INSERT INTO t VALUES (DEFAULT);
"""


def _setup(node, keyring, *, ext_in_redo=False):
    api.create_extension(node)
    # redo of CREATE EXTENSION drops the keys of WAL skipped relations (PG-1805)
    if not ext_in_redo:
        node.safe_sql("CHECKPOINT")
    node.setup_db_key(keyring)


@pytest.fixture
def minimal_node(tde_node, keyring_obj):
    _setup(tde_node, keyring_obj)
    return tde_node


def _tablespace(node, tmp_path):
    tsp = tmp_path / "tsp"
    tsp.mkdir()
    node.safe_sql(f"CREATE TABLESPACE tsp LOCATION {sql_literal(str(tsp))}")


def _crash(node):
    node.kill()
    node.poll_start()


@pytest.mark.bug("PG-1806")
@pytest.mark.parametrize(
    ("wal", "ext_in_redo"),
    [
        pytest.param(("minimal", "0"), False, id="minimal"),
        pytest.param(
            ("minimal", "0"),
            True,
            id="minimal-extension-in-redo",
            marks=pytest.mark.xfail(strict=True, raises=SqlError, reason=PG_1805),
        ),
        pytest.param(
            ("minimal", "2MB"),
            False,
            id="minimal-default-threshold",
            marks=pytest.mark.node_config({"wal_skip_threshold": "2MB"}),
        ),
        pytest.param(
            ("replica", "0"),
            False,
            id="replica",
            marks=pytest.mark.node_config({"wal_level": "replica", "max_wal_senders": "10"}),
        ),
    ],
)
def test_set_tablespace_and_index_after_crash(tde_node, keyring_obj, tmp_path, wal, ext_in_redo):
    node = tde_node
    _setup(node, keyring_obj, ext_in_redo=ext_in_redo)
    assert [node.sql_value("SHOW wal_level"), node.sql_value("SHOW wal_skip_threshold")] == list(wal)
    _tablespace(node, tmp_path)
    node.safe_sql("CREATE TABLE moved (id int) USING tde_heap; INSERT INTO moved VALUES (1)")
    node.safe_sql("""
        BEGIN;
        ALTER TABLE moved SET TABLESPACE tsp;
        CREATE TABLE originated (id int) USING tde_heap;
        INSERT INTO originated VALUES (1);
        CREATE UNIQUE INDEX originated_id ON originated (id) TABLESPACE tsp;
        COMMIT;
    """)

    _crash(node)

    for rel in ("moved", "originated", "originated_id"):
        assert node.is_encrypted(rel) is True, rel
    in_tsp = "SELECT relname FROM pg_class WHERE reltablespace = (SELECT oid FROM pg_tablespace WHERE spcname = 'tsp')"
    assert node.safe_sql(in_tsp + " ORDER BY 1") == [["moved"], ["originated_id"]]
    assert node.safe_sql("TABLE moved") == [["1"]]
    upsert = "INSERT INTO originated VALUES (1) ON CONFLICT (id) DO UPDATE SET id = originated.id + 1 RETURNING id"
    assert node.safe_sql(upsert) == [["2"]]
    assert node.safe_sql("TABLE originated") == [["2"]]


# each case: scripts run in order on one connection, then (query, rows or
# error pattern) checks after the crash; every case creates table t
@pytest.mark.parametrize(
    ("setup", "checks"),
    [
        pytest.param(
            ["BEGIN; CREATE TABLE t (id serial PRIMARY KEY) USING tde_heap; TRUNCATE t; COMMIT;"],
            [("SELECT count(*) FROM t", [["0"]])],
            id="truncate",
        ),
        pytest.param(
            [f"BEGIN; {TRUNC_INSERT} COMMIT;"],
            [("SELECT count(*), min(id) FROM t", [["1", "2"]])],
            id="truncate-insert",
        ),
        pytest.param(
            [f"BEGIN; {TRUNC_INSERT} PREPARE TRANSACTION 'p';", "COMMIT PREPARED 'p'"],
            [("SELECT count(*), min(id) FROM t", [["1", "2"]])],
            id="truncate-insert-prepare",
        ),
        pytest.param(
            [
                "SET wal_skip_threshold = '1GB'; BEGIN;"
                " CREATE TABLE t (id serial PRIMARY KEY) USING tde_heap;"
                " INSERT INTO t SELECT generate_series(1, 20000); COMMIT;"
            ],
            [("SELECT count(*), sum(id) FROM t", [["20000", "200010000"]])],
            id="large-insert-noskip",
        ),
        pytest.param(
            [TRUNC_COPY.replace("{savepoints}", "")],
            [("SELECT * FROM t ORDER BY id", COPY_ROWS)],
            id="truncate-copy",
        ),
        pytest.param(
            [TRUNC_COPY.replace("{savepoints}", "SAVEPOINT s; ALTER TABLE t SET TABLESPACE tsp; ROLLBACK TO s;")],
            [("SELECT * FROM t ORDER BY id", COPY_ROWS), IN_PG_DEFAULT],
            id="savepoint-set-tablespace",
        ),
        pytest.param(
            [
                TRUNC_COPY.replace(
                    "{savepoints}",
                    """
                    SAVEPOINT s;
                        ALTER TABLE t SET TABLESPACE tsp;
                        SAVEPOINT s2;
                            ALTER TABLE t SET TABLESPACE pg_default;
                        ROLLBACK TO s2;
                        SAVEPOINT s2;
                            ALTER TABLE t SET TABLESPACE pg_default;
                        RELEASE s2;
                    ROLLBACK TO s;
                    """,
                )
            ],
            [("SELECT * FROM t ORDER BY id", COPY_ROWS), IN_PG_DEFAULT],
            id="nested-savepoint-set-tablespace",
        ),
        pytest.param(
            [
                """
                BEGIN;
                CREATE TABLE t (c int PRIMARY KEY) USING tde_heap;
                SAVEPOINT q; INSERT INTO t VALUES (1); ROLLBACK TO q;
                CHECKPOINT;
                INSERT INTO t VALUES (1);
                INSERT INTO t VALUES (2);
                COMMIT;
                """
            ],
            [
                ("SELECT c FROM t ORDER BY c", [["1"], ["2"]]),
                ("INSERT INTO t VALUES (2)", "duplicate key value violates unique constraint"),
            ],
            id="unique-index-lp-dead",
        ),
        pytest.param(
            [INS_TRIGGERS],
            [
                (
                    "SELECT id2 FROM t ORDER BY id2",
                    [[v] for v in ("30000", "30001", "30002")]
                    + [[f"triggered row {w}{v}"] for w in ("after", "before") for v in ("30000", "30001", "30002")],
                )
            ],
            id="copy-row-triggers",
        ),
        pytest.param(
            [TRUNC_TRIGGERS],
            [("SELECT * FROM t ORDER BY id", [["3", "triggered stat after"], *COPY_ROWS])],
            id="truncate-statement-triggers",
        ),
    ],
)
def test_wal_skip_after_crash(minimal_node, tmp_path, setup, checks):
    node = minimal_node
    _tablespace(node, tmp_path)
    copy = tmp_path / "copy.txt"
    copy.write_text("".join(f"{a},{b}\n" for a, b in COPY_ROWS))

    with node.connect() as c:
        for script in setup:
            c.safe_sql(script.replace("{copy}", sql_literal(str(copy))))

    _crash(node)

    assert node.is_encrypted("t") is True
    assert node.is_encrypted("t_pkey") is True
    for query, want in checks:
        if isinstance(want, str):
            node.expect_error(want, query)
        else:
            assert node.safe_sql(query) == want, query


def test_temp_table_crash_leaves_no_orphan_files(minimal_node):
    node = minimal_node
    db_dir = node.datadir / "base" / node.sql_value("SELECT oid FROM pg_database WHERE datname = current_database()")
    temp_file = re.compile(r"^t\d+_\d+")

    def files():
        return {p.name for p in db_dir.iterdir()}

    with node.connect() as c:
        c.safe_sql("""
            CREATE TEMP TABLE temp_t (id serial PRIMARY KEY, v text) USING tde_heap;
            INSERT INTO temp_t (v) SELECT g::text FROM generate_series(1, 100) g;
        """)
        assert c.sql_value("SELECT pg_tde_is_encrypted('temp_t')") == "t"
        assert any(temp_file.match(f) for f in files())
        node.kill()
    node.poll_start()

    assert [f for f in files() if temp_file.match(f)] == []
    on_disk = {f for f in files() if f.isdigit()}
    referenced = node.safe_sql("""
        SELECT pg_relation_filepath(oid) FROM pg_class
        WHERE reltablespace = 0 AND relpersistence <> 't' AND pg_relation_filepath(oid) IS NOT NULL
    """)
    assert on_disk == {r[0].rsplit("/", 1)[1] for r in referenced}
