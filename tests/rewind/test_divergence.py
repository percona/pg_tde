from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest

from pgtde import api
from pgtde.node import TdeNode
from pgtde.rewind import check_asymmetric_tables, create_asymmetric_tables, create_tail_block, diverge_tail_block
from pgtde.wal import archive_config

# SQL runs on the node of its hook; callables get (old primary, new primary),
# in setup the standby does not exist yet and they get (old primary, None)
Step = str | Callable[[TdeNode, TdeNode | None], None]


@dataclass
class Divergence:
    setup: tuple[Step, ...] = ()
    before_promotion: tuple[Step, ...] = ()
    source: tuple[Step, ...] = ()
    target: tuple[Step, ...] = ()
    # (query, value) on the rewound node, with and without seqscans
    checks: tuple[tuple[str, str], ...] = ()
    mode: str = "local"
    config: dict[str, str] = field(default_factory=dict)
    wal_encrypt: bool = True


def _run(node, steps, p, s):
    for step in steps:
        if isinstance(step, str):
            node.safe_sql(step)
        else:
            step(p, s)


def _check(node, checks):
    with node.connect() as c:
        for seqscan in ("on", "off"):
            c.safe_sql(f"SET enable_seqscan = {seqscan}")
            for query, want in checks:
                assert c.sql_value(query) == want, f"{query} (enable_seqscan={seqscan})"


def _rotate_key(node, key):
    api.create_key(node, key, "db-provider")
    api.set_key(node, key, "db-provider")


def _crash(node):
    node.kill()
    node.poll_start()


def _restart_both(p, s):
    p.restart()
    s.restart()


def _loop(body, n):
    return f"DO $$ BEGIN FOR i IN 1..{n} LOOP {body} END LOOP; END $$"


T1 = "CREATE TABLE t1 (id int); INSERT INTO t1 SELECT generate_series(1, 10000)"
ENCRYPTED_RELS = "SELECT bool_and(pg_tde_is_encrypted(oid)) FROM pg_class WHERE relkind = 'r' AND relname ~ '{}'"
# rel_1..rel_5 dropped on the old primary only, rel_41.. and new_1..new_25 on the new one
KEPT_RELS = [f"rel_{i}" for i in range(1, 41)] + [f"new_{i}" for i in range(26, 51)]
ROWS_IN_KEPT = "SELECT sum(n) FROM (" + " UNION ALL ".join(f"SELECT count(*) AS n FROM {t}" for t in KEPT_RELS) + ") x"


def _both_wal(scenario, name, marks=(), plain_marks=()):
    # ppg ran these with plain WAL as well
    return [
        pytest.param(scenario, id=name, marks=marks),
        pytest.param(replace(scenario, wal_encrypt=False), id=f"{name}_plain_wal", marks=plain_marks),
    ]


SCENARIOS = [
    pytest.param(
        Divergence(
            setup=(T1,),
            source=("INSERT INTO t1 VALUES (999999)",),
            target=(
                _loop(
                    "BEGIN INSERT INTO t1 VALUES (i + 1000000); RAISE EXCEPTION 'abort';"
                    " EXCEPTION WHEN OTHERS THEN NULL; END;",
                    500,
                ),
            ),
            checks=(("SELECT count(*) FROM t1", "10001"), ("SELECT count(*) FROM t1 WHERE id > 999999", "0")),
        ),
        id="minimal",
    ),
    pytest.param(
        Divergence(
            setup=("CREATE TABLE heavy_t (id int); INSERT INTO heavy_t SELECT generate_series(1, 10000)",),
            source=(
                "UPDATE heavy_t SET id = id + 1",
                "DELETE FROM heavy_t WHERE id % 3 = 0",
                "CREATE INDEX heavy_idx ON heavy_t (id)",
                "REINDEX TABLE heavy_t",
            ),
            target=("UPDATE heavy_t SET id = -id WHERE id % 7 = 0",),
            checks=(
                ("SELECT count(*) FROM heavy_t WHERE id > 0", "6667"),
                ("SELECT sum(id) FROM heavy_t", "33346667"),
            ),
            mode="restore",
        ),
        id="heavy",
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLE base_t (id int); INSERT INTO base_t SELECT generate_series(1, 1000)",
                _loop(
                    "EXECUTE format('CREATE TABLE rel_%s (id int, v text)', i);"
                    " EXECUTE format('INSERT INTO rel_%s SELECT g, md5(g::text) FROM generate_series(1, 100) g', i);",
                    50,
                ),
            ),
            source=(
                "INSERT INTO base_t SELECT generate_series(1, 200000)",
                "UPDATE base_t SET id = id + 1",
                "DELETE FROM base_t WHERE id % 2 = 0",
                "CHECKPOINT",
                _loop("EXECUTE format('UPDATE rel_%s SET v = ''upd'' WHERE id %% 10 = 0', i);", 50),
                _loop(
                    "EXECUTE format('CREATE TABLE new_%s (id int, v text)', i);"
                    " EXECUTE format('INSERT INTO new_%s SELECT g, md5(g::text) FROM generate_series(1, 1000) g', i);",
                    50,
                ),
                _loop("EXECUTE format('DROP TABLE new_%s, rel_%s', i, i + 40);", 10),
                _loop("EXECUTE format('DROP TABLE new_%s', i + 10);", 15),
                "VACUUM FULL rel_1",
            ),
            target=(
                _loop("EXECUTE format('CREATE TABLE tgt_%s AS SELECT generate_series(1, 10) AS id', i);", 20),
                _loop("EXECUTE format('DROP TABLE rel_%s', i);", 5),
                "DELETE FROM base_t WHERE id < 500",
            ),
            checks=(
                ("SELECT count(*) FROM base_t", "100500"),
                ("SELECT count(*) FROM pg_class WHERE relkind = 'r' AND relname ~ '^rel_[0-9]+$'", "40"),
                ("SELECT count(*) FROM pg_class WHERE relkind = 'r' AND relname ~ '^new_[0-9]+$'", "25"),
                ("SELECT count(*) FROM pg_class WHERE relname ~ '^tgt_[0-9]+$'", "0"),
                (ROWS_IN_KEPT, "29000"),
                (ENCRYPTED_RELS.format("^(rel|new)_[0-9]+$"), "t"),
            ),
        ),
        id="many_relations",
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLE toast_base (id int, data text);"
                " ALTER TABLE toast_base ALTER COLUMN data SET STORAGE EXTERNAL;"
                " INSERT INTO toast_base SELECT g, repeat('b', 5000) FROM generate_series(1, 10) g",
            ),
            source=(
                "CREATE TABLE toast_t (id int, data text);"
                " ALTER TABLE toast_t ALTER COLUMN data SET STORAGE EXTERNAL;"
                " INSERT INTO toast_t SELECT g, repeat(md5(g::text), 1000) FROM generate_series(1, 500) g",
                "UPDATE toast_base SET data = repeat('s', 6000) WHERE id <= 5",
                "CREATE TABLE part_t (id int, created date) PARTITION BY RANGE (created);"
                " CREATE TABLE part_2024 PARTITION OF part_t FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');"
                " CREATE TABLE part_2025 PARTITION OF part_t FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');"
                " INSERT INTO part_t SELECT g, '2024-06-01'::date + (g % 365) FROM generate_series(1, 10000) g",
            ),
            target=(
                "UPDATE toast_base SET data = repeat('t', 7000) WHERE id > 5",
                "CREATE TABLE part_tgt (id int) PARTITION BY RANGE (id);"
                " CREATE TABLE part_tgt_1 PARTITION OF part_tgt FOR VALUES FROM (0) TO (100);"
                " INSERT INTO part_tgt SELECT generate_series(0, 99)",
            ),
            checks=(
                ("SELECT sum(length(data)) FROM toast_t", "16000000"),
                ("SELECT sum(length(data)) FROM toast_base", "55000"),
                ("SELECT pg_tde_is_encrypted(reltoastrelid) FROM pg_class WHERE relname = 'toast_t'", "t"),
                ("SELECT count(*) FROM part_t", "10000"),
                ("SELECT count(*) FROM part_2025", "4077"),
                (
                    "SELECT bool_and(pg_tde_is_encrypted(inhrelid)) FROM pg_inherits"
                    " WHERE inhparent = 'part_t'::regclass",
                    "t",
                ),
                ("SELECT to_regclass('part_tgt') IS NULL", "t"),
            ),
        ),
        id="toast_and_partitions",
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLE idx_t (id int, attrs jsonb, doc tsvector);"
                " INSERT INTO idx_t SELECT g, jsonb_build_object('k', g), to_tsvector('simple', 'base')"
                " FROM generate_series(1, 500) g;"
                " CREATE INDEX idx_gin ON idx_t USING gin (attrs);"
                " CREATE INDEX idx_gist ON idx_t USING gist (doc);"
                " CREATE INDEX idx_partial ON idx_t (id) WHERE id > 100;"
                " CREATE INDEX idx_expr ON idx_t ((id * 2))",
            ),
            source=(
                "INSERT INTO idx_t SELECT g, jsonb_build_object('k', g), to_tsvector('simple', 'source')"
                " FROM generate_series(501, 1000) g",
                "REINDEX TABLE idx_t",
            ),
            target=(
                "INSERT INTO idx_t SELECT g, jsonb_build_object('k', g), to_tsvector('simple', 'target')"
                " FROM generate_series(2000, 2500) g",
                "REINDEX INDEX idx_gin",
            ),
            checks=(
                ("SELECT count(*) FROM idx_t", "1000"),
                ("""SELECT count(*) FROM idx_t WHERE attrs @> '{"k": 777}'""", "1"),
                ("SELECT count(*) FROM idx_t WHERE doc @@ to_tsquery('simple', 'source')", "500"),
                ("SELECT count(*) FROM idx_t WHERE doc @@ to_tsquery('simple', 'target')", "0"),
                ("SELECT count(*) FROM idx_t WHERE id > 100", "900"),
                ("SELECT count(*) FROM idx_t WHERE id * 2 = 1000", "1"),
                (
                    "SELECT bool_and(pg_tde_is_encrypted(indexrelid)) FROM pg_index WHERE indrelid = 'idx_t'::regclass",
                    "t",
                ),
            ),
            mode="remote",
        ),
        id="indexes",
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLE churn_t (id int PRIMARY KEY, v text);"
                " INSERT INTO churn_t SELECT g, md5(g::text) FROM generate_series(1, 5000) g;"
                " CREATE INDEX churn_v ON churn_t (v)",
                "CREATE TABLE trunc_t (id int); INSERT INTO trunc_t SELECT generate_series(1, 1000)",
            ),
            source=(
                "DELETE FROM churn_t WHERE id % 2 = 0",
                "VACUUM FULL churn_t",
                "CLUSTER churn_t USING churn_t_pkey",
                "REINDEX TABLE churn_t",
                "CREATE INDEX CONCURRENTLY churn_v2 ON churn_t (v, id)",
                "ALTER TABLE churn_t ADD COLUMN c int",
                "TRUNCATE trunc_t",
                "INSERT INTO trunc_t SELECT generate_series(1, 300)",
                lambda p, s: _rotate_key(s, "source-key"),
                "INSERT INTO churn_t SELECT g, 'after-rotation' FROM generate_series(10001, 10100) g",
            ),
            target=(
                lambda p, s: _rotate_key(p, "target-key"),
                "VACUUM FULL",
                "REINDEX TABLE churn_t",
                "TRUNCATE trunc_t",
                "DELETE FROM churn_t",
            ),
            checks=(
                ("SELECT count(*) FROM churn_t", "2600"),
                ("SELECT count(*) FROM churn_t WHERE v = 'after-rotation'", "100"),
                ("SELECT count(*) FROM trunc_t", "300"),
                ("SELECT count(*) FROM pg_attribute WHERE attrelid = 'churn_t'::regclass AND attname = 'c'", "1"),
                ("SELECT key_name FROM pg_tde_key_info()", "source-key"),
                (ENCRYPTED_RELS.format("^(churn|trunc)_t$"), "t"),
            ),
            mode="restore",
        ),
        id="churn",
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLESPACE ts1 LOCATION ''",
                "CREATE TABLE ts_t (id int, v text) TABLESPACE ts1;"
                " INSERT INTO ts_t SELECT g, repeat('x', 200) FROM generate_series(1, 1000) g;"
                " DELETE FROM ts_t WHERE id % 2 = 0",
            ),
            source=("VACUUM FULL ts_t", "INSERT INTO ts_t SELECT g, 'source' FROM generate_series(1, 50) g"),
            target=("VACUUM FULL ts_t", "INSERT INTO ts_t SELECT g, 'target' FROM generate_series(1, 70) g"),
            checks=(
                ("SELECT count(*) FROM ts_t", "550"),
                ("SELECT count(*) FROM ts_t WHERE v = 'target'", "0"),
                ("SELECT pg_tde_is_encrypted('ts_t')", "t"),
            ),
        ),
        id="tablespace_vacuum_full",
        marks=pytest.mark.pg_min(17),
    ),
    pytest.param(
        Divergence(
            setup=("CREATE TABLE logged_t (id int); INSERT INTO logged_t SELECT generate_series(1, 100)",),
            source=(
                "CREATE UNLOGGED TABLE u_src (id int); INSERT INTO u_src SELECT generate_series(1, 10000)",
                "INSERT INTO logged_t SELECT generate_series(101, 200)",
            ),
            target=(
                "CREATE UNLOGGED TABLE u_tgt (id int); INSERT INTO u_tgt VALUES (1)",
                "CREATE TEMP TABLE temp_t (id int); INSERT INTO temp_t VALUES (2)",
            ),
            checks=(
                ("SELECT count(*) FROM logged_t", "200"),
                ("SELECT relpersistence FROM pg_class WHERE relname = 'u_src'", "u"),
                ("SELECT pg_tde_is_encrypted('u_src')", "t"),
                ("SELECT to_regclass('u_tgt') IS NULL", "t"),
            ),
            mode="restore",
        ),
        id="unlogged_and_temp",
    ),
    pytest.param(
        Divergence(
            setup=("CREATE TABLE tde_2pc (id int, val text); INSERT INTO tde_2pc VALUES (1, 'initial')",),
            before_promotion=("BEGIN; INSERT INTO tde_2pc VALUES (2, 'prepared'); PREPARE TRANSACTION 'tde_trx'",),
            source=("COMMIT PREPARED 'tde_trx'", "INSERT INTO tde_2pc VALUES (3, 'post_commit')"),
            target=("INSERT INTO tde_2pc VALUES (99, 'orphan')",),
            checks=(
                ("SELECT string_agg(id::text, ',' ORDER BY id) FROM tde_2pc", "1,2,3"),
                ("SELECT count(*) FROM pg_prepared_xacts", "0"),
            ),
            mode="restore",
            config={"max_prepared_transactions": "10"},
        ),
        id="two_phase",
    ),
    pytest.param(
        Divergence(
            setup=("CREATE TABLE crash_t (id int); INSERT INTO crash_t SELECT generate_series(1, 200)",),
            source=(
                "INSERT INTO crash_t SELECT generate_series(201, 500)",
                "UPDATE crash_t SET id = id + 1",
                lambda p, s: _crash(s),
            ),
            checks=(("SELECT count(*) FROM crash_t", "500"), ("SELECT sum(id) FROM crash_t", "125750")),
        ),
        id="crash_on_source",
    ),
    *_both_wal(
        Divergence(
            setup=(T1,),
            before_promotion=(_restart_both,),
            source=("INSERT INTO t1 VALUES (999999)",),
            checks=(("SELECT count(*) FROM t1", "10001"),),
            mode="restore",
        ),
        "restart_before_promotion",
        plain_marks=pytest.mark.bug("PG-2329"),
    ),
    *_both_wal(
        Divergence(
            setup=(T1,),
            before_promotion=(lambda p, s: p.restart(),),
            source=("INSERT INTO t1 VALUES (999999)", "CHECKPOINT"),
            # restarting the old primary between divergence and rewind kept its stale state
            target=("INSERT INTO t1 VALUES (-1)", lambda p, s: p.restart()),
            checks=(("SELECT count(*) FROM t1", "10001"), ("SELECT count(*) FROM t1 WHERE id < 0", "0")),
            mode="restore",
        ),
        "restart_target_before_rewind",
        marks=[pytest.mark.bug("PG-2330"), pytest.mark.bug("PG-2357")],
        plain_marks=[pytest.mark.bug("PG-2330"), pytest.mark.bug("PG-2357")],
    ),
    pytest.param(
        Divergence(
            setup=(
                "CREATE TABLE comp_t (id int, payload text);"
                " INSERT INTO comp_t SELECT g, repeat(md5(g::text), 10) FROM generate_series(1, 500) g",
            ),
            # full page images after the checkpoints, compressed inside encrypted records
            source=(
                "CHECKPOINT",
                "UPDATE comp_t SET payload = md5(payload)",
                "INSERT INTO comp_t SELECT g, md5(g::text) FROM generate_series(501, 1000) g",
            ),
            target=("CHECKPOINT", "UPDATE comp_t SET payload = 'target'"),
            checks=(
                ("SELECT count(*) FROM comp_t", "1000"),
                ("SELECT sum(length(payload)) FROM comp_t", "32000"),
            ),
            config={"wal_compression": "lz4"},
        ),
        id="wal_compression",
    ),
    pytest.param(
        Divergence(
            before_promotion=(lambda p, s: create_tail_block(p),),
            source=(diverge_tail_block,),
            checks=(
                ("SELECT count(*) FROM tail_t", "2000"),
                ("SELECT count(*) FROM block_t", "1000"),
                (ENCRYPTED_RELS.format("^(tail|block)_t$"), "t"),
            ),
            wal_encrypt=False,
        ),
        id="plain_wal",
    ),
]


# One divergence on the new primary and/or the old one, then pg_tde_rewind.
# The rewound node must show the new primary's state, before and after a
# restart; tables created on either side after the promotion tell which
# history won.
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_rewind_after_divergence(scenario, file_rewind_driver, pg_install_dir, tmp_path):
    config = dict(scenario.config)
    if scenario.mode == "restore":
        archive = tmp_path / "archive"
        archive.mkdir()
        config |= archive_config(f"{pg_install_dir}/bin", archive, restore=True)
        # the rewind has to fetch recycled target WAL
        config["wal_keep_size"] = "0"
    with file_rewind_driver(config=config, wal_encrypt=scenario.wal_encrypt) as rw:
        p = rw.setup_primary()
        _run(p, scenario.setup, p, None)
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        _run(p, scenario.before_promotion, p, s)
        rw.promote_standby()
        _run(s, scenario.source, p, s)
        _run(p, scenario.target, p, s)
        create_asymmetric_tables(p, s)

        rw.run_rewind(scenario.mode)

        _check(p, scenario.checks)
        check_asymmetric_tables(p)
        p.restart()
        _check(p, scenario.checks)
