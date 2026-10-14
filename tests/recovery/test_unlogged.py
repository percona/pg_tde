import pytest
from stormweaver import SqlError

from pgtde.sql import sql_literal


def _forks(node, rel):
    main = node.relation_filepath(rel)
    return {f: main.with_name(main.name + f) for f in ("", "_init", "_vm", "_fsm")}


def _nextvals(node, seq, n):
    return [node.sql_value(f"SELECT nextval('{seq}')") for _ in range(n)]


# from upstream src/test/recovery/t/014_unlogged_reinit.pl
def test_unlogged_tables(tde_node_db, tmp_path):
    node = tde_node_db
    tsp = tmp_path / "tsp"
    tsp.mkdir()
    node.safe_sql(f"CREATE TABLESPACE tsp LOCATION {sql_literal(str(tsp))}")
    node.safe_sql("""
        CREATE UNLOGGED TABLE t (x int PRIMARY KEY) USING tde_heap;
        INSERT INTO t SELECT generate_series(1, 4);
        CREATE UNLOGGED TABLE t_tsp (x int PRIMARY KEY) USING tde_heap TABLESPACE tsp;
        INSERT INTO t_tsp SELECT generate_series(1, 4);
        CREATE UNLOGGED SEQUENCE s OWNED BY t.x;
        ALTER SEQUENCE s INCREMENT 2;
        CHECKPOINT;
    """)
    assert _nextvals(node, "s", 2) == ["1", "3"]

    tables = ("t", "t_tsp")
    rels = (*tables, "s")
    forks = {r: _forks(node, r) for r in rels}
    for r in rels:
        assert node.is_encrypted(r) is True, r
        assert forks[r][""].exists(), r
        assert forks[r]["_init"].exists(), r

    node.stop(mode="immediate")
    for r in tables:
        forks[r]["_vm"].write_bytes(b"TEST_VM\n")
        forks[r]["_fsm"].write_bytes(b"TEST_FSM\n")
    for r in rels:
        forks[r][""].unlink()
    node.start()

    # main fork copied from the init fork, vm and fsm removed
    for r in rels:
        assert forks[r]["_init"].exists(), r
        assert forks[r][""].exists(), r
        assert node.is_encrypted(r) is True, r
    for r in tables:
        assert not forks[r]["_vm"].exists(), r
        assert not forks[r]["_fsm"].exists(), r

    assert node.safe_sql("TABLE t") == []
    assert node.safe_sql("TABLE t_tsp") == []
    assert _nextvals(node, "s", 2) == ["1", "3"]

    node.safe_sql("INSERT INTO t SELECT generate_series(1, 4)")
    node.safe_sql("INSERT INTO t_tsp VALUES (10)")
    assert node.safe_sql("TABLE t") == [[str(i)] for i in range(1, 5)]
    assert node.safe_sql("TABLE t_tsp") == [["10"]]


@pytest.mark.bug("PG-1805")
@pytest.mark.node_config({"checkpoint_timeout": "1h"})
@pytest.mark.parametrize(
    ("persistence", "identity", "ext_in_redo", "vals", "min_id"),
    [
        pytest.param("UNLOGGED", True, False, [["after"]], "1", id="unlogged-identity"),
        pytest.param(
            "UNLOGGED",
            True,
            True,
            [["after"]],
            "1",
            id="unlogged-identity-extension-in-redo",
            marks=pytest.mark.xfail(
                strict=True,
                raises=SqlError,
                reason="TODO: PG-1805 only partly fixed -- redo of INSTALL_EXTENSION runs "
                "principal_key_startup_cleanup and drops relation keys created later "
                "(unlogged init forks / WAL-skipped tables); may need its own ticket",
            ),
        ),
        pytest.param("", True, False, [["before"], ["after"]], "1", id="logged-identity"),
        pytest.param("UNLOGGED", False, False, [["after"]], "2", id="unlogged-plain"),
    ],
)
def test_identity_after_unlogged_reinit(tde_node_db, persistence, identity, ext_in_redo, vals, min_id):
    node = tde_node_db
    if not ext_in_redo:
        node.safe_sql("CHECKPOINT")
    col = "id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY" if identity else "id int"
    node.safe_sql(f"CREATE {persistence} TABLE t ({col}, val text) USING tde_heap")

    def insert(n, val):
        if identity:
            node.safe_sql(f"INSERT INTO t (val) VALUES ('{val}')")
        else:
            node.safe_sql(f"INSERT INTO t VALUES ({n}, '{val}')")

    if identity:
        # new relfilenodes for the table and the identity sequence
        node.safe_sql("TRUNCATE t RESTART IDENTITY")
        assert node.is_encrypted("t_id_seq") is True
    insert(1, "before")

    # redo replays the init fork creation
    node.kill()
    node.poll_start()

    insert(2, "after")
    assert node.safe_sql("SELECT val FROM t ORDER BY id") == vals
    assert node.sql_value("SELECT min(id) FROM t") == min_id
