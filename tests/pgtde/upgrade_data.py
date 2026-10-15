from typing import NamedTuple

from pgtde import api

TOAST_SQL = "repeat('abcdefghijklmnopqrstuvwxyz', 10000)"
RICH_CONFIG = {"default_table_access_method": "tde_heap"}


def global_key(node, keyring, key="db-key"):
    node.setup_server_key(keyring)
    api.create_key(node, key, "global-provider", scope="global")
    api.set_key(node, key, "global-provider", scope="global")


class Churn(NamedTuple):
    sql: list[str]
    query: str
    expected: list[list[str]]


# churn leaving empty key files / empty key slots behind
CHURN = {
    "vacuum_full": Churn(
        [
            "CREATE TABLE vf_t (id int) USING tde_heap",
            "INSERT INTO vf_t SELECT generate_series(1, 50)",
            # database wide: the shared catalogs get an empty 0_keys
            "VACUUM FULL",
        ],
        "SELECT count(*), sum(id) FROM vf_t",
        [["50", "1275"]],
    ),
    "drop_table": Churn(
        [
            "CREATE TABLE active_t (id int) USING tde_heap",
            "INSERT INTO active_t SELECT generate_series(1, 30)",
            # last, so no later relation reuses the freed key slot
            "CREATE TABLE drop_t (id int) USING tde_heap",
            "INSERT INTO drop_t VALUES (1)",
            "DROP TABLE drop_t",
        ],
        "SELECT count(*), sum(id) FROM active_t",
        [["30", "465"]],
    ),
    "ghost": Churn(
        [
            "CREATE TABLE ghost_t (id int) USING tde_heap",
            "INSERT INTO ghost_t VALUES (1)",
            "DROP TABLE ghost_t",
            "CREATE TABLE ghost_t (id int) USING tde_heap",
            "INSERT INTO ghost_t VALUES (2)",
            "VACUUM FULL",
        ],
        "SELECT id FROM ghost_t",
        [["2"]],
    ),
}


def churn(node, kind):
    for sql in CHURN[kind].sql:
        node.safe_sql(sql)


def check_churn(node, kind):
    c = CHURN[kind]
    assert node.safe_sql(c.query) == c.expected, kind


def build_rich(node, keyring, tmp_path):
    # one cluster with the schema objects and key setups an upgrade has to carry
    node.setup_server_key(keyring)
    api.add_provider(node, tmp_path / "spare.keys", "spare-provider", scope="global")
    for gen in (1, 2, 3):
        api.create_key(node, f"key-gen{gen}", "global-provider", scope="global")
        api.set_key(node, f"key-gen{gen}", "global-provider", scope="global")
        if gen == 1:
            node.safe_sql("CREATE TABLE rot_t (id int PRIMARY KEY, gen text) USING tde_heap")
        node.safe_sql(f"INSERT INTO rot_t VALUES ({gen}, 'gen{gen}')")

    parent_am = " USING tde_heap" if node.pg_major >= 17 else ""
    node.safe_sql(f"""
        CREATE TABLE plain_t (id int PRIMARY KEY, v text) USING heap;
        INSERT INTO plain_t SELECT i, md5(i::text) FROM generate_series(1, 100) i;
        CREATE TABLE default_am_t (id int);
        INSERT INTO default_am_t SELECT generate_series(1, 10);
        CREATE TABLE part_t (id int, ts date) PARTITION BY RANGE (ts){parent_am};
        CREATE TABLE part_t_2024 PARTITION OF part_t FOR VALUES FROM ('2024-01-01') TO ('2025-01-01') USING tde_heap;
        CREATE TABLE part_t_2025 PARTITION OF part_t FOR VALUES FROM ('2025-01-01') TO ('2026-01-01') USING tde_heap;
        INSERT INTO part_t VALUES (1, '2024-06-01'), (2, '2024-12-31'), (3, '2025-03-01'), (4, '2025-09-15');
        CREATE TABLE parent_t (id int PRIMARY KEY, label text) USING tde_heap;
        CREATE TABLE child_t (id int PRIMARY KEY, parent_id int REFERENCES parent_t (id) ON DELETE CASCADE)
            USING tde_heap;
        INSERT INTO parent_t VALUES (1, 'a'), (2, 'b'), (3, 'c');
        INSERT INTO child_t VALUES (10, 1), (11, 1), (12, 2);
        CREATE TABLE idx_t (id int, txt text, n int) USING tde_heap;
        INSERT INTO idx_t SELECT i, md5(i::text), i % 100 FROM generate_series(1, 500) i;
        CREATE INDEX idx_t_btree ON idx_t USING btree (id);
        CREATE INDEX idx_t_hash ON idx_t USING hash (txt);
        CREATE INDEX idx_t_brin ON idx_t USING brin (n);
        CREATE SEQUENCE order_seq START 1000;
        CREATE TABLE orders (
            id int DEFAULT nextval('order_seq') PRIMARY KEY,
            amount numeric(12, 2) CHECK (amount > 0),
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'shipped', 'done'))
        ) USING tde_heap;
        CREATE INDEX orders_pending ON orders (id) WHERE status = 'pending';
        INSERT INTO orders (amount, status)
            SELECT i * 3.14, (ARRAY['pending', 'shipped', 'done'])[i % 3 + 1] FROM generate_series(1, 300) i;
        CREATE VIEW v_pending AS SELECT id, amount FROM orders WHERE status = 'pending';
        CREATE TABLE toast_t (id int, payload text) USING tde_heap;
        ALTER TABLE toast_t ALTER COLUMN payload SET STORAGE EXTERNAL;
        INSERT INTO toast_t VALUES (1, {TOAST_SQL});
        CREATE UNLOGGED TABLE unlogged_t (id int) USING tde_heap;
        INSERT INTO unlogged_t VALUES (1), (2), (3);
    """)
    for kind in CHURN:
        churn(node, kind)

    node.safe_sql("CREATE DATABASE dbkey")
    with node.connect(db="dbkey") as c:
        api.create_extension(c)
        api.create_key(c, "dbkey-key", "global-provider", scope="global")
        api.set_key(c, "dbkey-key", "global-provider", scope="global")
        c.safe_sql("CREATE TABLE enc_t (id int) USING tde_heap; INSERT INTO enc_t SELECT generate_series(1, 20)")

    node.safe_sql("CREATE DATABASE dbprov")
    with node.connect(db="dbprov") as c:
        api.create_extension(c)
        api.add_provider(c, tmp_path / "db.keys", "db-provider")
        api.create_key(c, "db-key", "db-provider")
        api.set_key(c, "db-key", "db-provider")
        c.safe_sql(f"""
            CREATE TABLE enc_t (k int PRIMARY KEY) USING tde_heap;
            INSERT INTO enc_t VALUES (1), (2);
            CREATE TABLE part_enc (id int) PARTITION BY RANGE (id){parent_am};
            CREATE TABLE part_enc_1 PARTITION OF part_enc FOR VALUES FROM (0) TO (100) USING tde_heap;
            CREATE TABLE part_enc_2 PARTITION OF part_enc FOR VALUES FROM (100) TO (200) USING tde_heap;
            INSERT INTO part_enc VALUES (10), (20), (110), (120);
        """)

    node.safe_sql("CREATE DATABASE custom")
    with node.connect(db="custom") as c:
        c.safe_sql("""
            CREATE SCHEMA vault;
            CREATE EXTENSION pg_tde SCHEMA vault;
            SELECT vault.pg_tde_create_key_using_global_key_provider('custom-key', 'global-provider');
            SELECT vault.pg_tde_set_key_using_global_key_provider('custom-key', 'global-provider');
            CREATE TABLE enc_t (id int) USING tde_heap;
            INSERT INTO enc_t VALUES (99);
        """)


def encrypted_old(upgrade, factory, keyring, name="old", *, wal_encrypt=False, **kw):
    # old cluster with server and database key, t_enc of 100 rows
    node = upgrade.old_node(factory, name, **kw)
    global_key(node, keyring)
    if wal_encrypt:
        api.set_wal_encrypt(node, True)
        node.restart()
    node.safe_sql(
        "CREATE TABLE t_enc (k int PRIMARY KEY, v text) USING tde_heap;"
        "INSERT INTO t_enc SELECT i, md5(i::text) FROM generate_series(1, 100) i"
    )
    return node


def t_enc_rows(node):
    return node.sql_value("SELECT count(*) FROM t_enc WHERE v = md5(k::text)")


def _encrypted(conn, *rels):
    for rel in rels:
        assert api.is_encrypted(conn, rel) is True, rel


def check_rich(node):
    # read only, can run more than once
    assert api.server_key_info(node)[1:] == ["global-provider", "server-key"]
    assert api.key_info(node)[1:] == ["global-provider", "key-gen3"]
    assert sorted(r[1] for r in api.list_providers(node, scope="global")) == ["global-provider", "spare-provider"]
    assert api.list_providers(node) == []
    assert node.safe_sql("SELECT * FROM rot_t ORDER BY id") == [["1", "gen1"], ["2", "gen2"], ["3", "gen3"]]

    assert node.sql_value("SELECT count(*) FROM plain_t WHERE v = md5(id::text)") == "100"
    assert api.is_encrypted(node, "plain_t") is False
    assert node.safe_sql("SELECT count(*), sum(id) FROM default_am_t") == [["10", "55"]]
    assert node.safe_sql("SELECT id FROM part_t ORDER BY id") == [["1"], ["2"], ["3"], ["4"]]
    assert node.sql_value("SELECT count(*) FROM part_t_2024") == "2"
    assert node.safe_sql("SELECT * FROM child_t ORDER BY id") == [["10", "1"], ["11", "1"], ["12", "2"]]
    with node.connect() as c:
        c.safe_sql("SET enable_seqscan = off")
        assert c.sql_value("SELECT count(*) FROM idx_t WHERE id = 250") == "1"
        assert c.sql_value("SELECT id FROM idx_t WHERE txt = md5('250')") == "250"
        assert c.sql_value("SELECT count(*) FROM idx_t WHERE n = 50") == "5"
    assert node.safe_sql("SELECT count(*), max(id) FROM orders") == [["300", "1299"]]
    assert node.sql_value("SELECT last_value FROM order_seq") == "1299"
    assert node.sql_value("SELECT count(*) FROM v_pending") == "100"
    assert node.sql_value("SELECT pg_get_indexdef('orders_pending'::regclass)").endswith(
        "WHERE (status = 'pending'::text)"
    )
    assert node.sql_value(f"SELECT payload = {TOAST_SQL} FROM toast_t") == "t"
    toast = node.sql_value("SELECT reltoastrelid::regclass FROM pg_class WHERE relname = 'toast_t'")
    assert node.sql_value(f"SELECT pg_relation_size('{toast}') > 0") == "t"
    assert node.sql_value("SELECT count(*) FROM unlogged_t") == "3"
    _encrypted(
        node,
        "rot_t",
        "default_am_t",
        "part_t_2024",
        "part_t_2025",
        "parent_t",
        "child_t",
        "idx_t",
        "idx_t_btree",
        "idx_t_hash",
        "idx_t_brin",
        "orders",
        "orders_pending",
        "toast_t",
        toast,
        "unlogged_t",
    )
    for kind in CHURN:
        check_churn(node, kind)

    with node.connect(db="dbkey") as c:
        assert api.key_info(c)[1:] == ["global-provider", "dbkey-key"]
        assert c.safe_sql("SELECT count(*), sum(id) FROM enc_t") == [["20", "210"]]
        _encrypted(c, "enc_t")
    with node.connect(db="dbprov") as c:
        assert [r[1] for r in api.list_providers(c)] == ["db-provider"]
        assert api.key_info(c)[1:] == ["db-provider", "db-key"]
        assert c.safe_sql("SELECT k FROM enc_t ORDER BY k") == [["1"], ["2"]]
        assert c.safe_sql("SELECT id FROM part_enc ORDER BY id") == [["10"], ["20"], ["110"], ["120"]]
        _encrypted(c, "enc_t", "part_enc_1", "part_enc_2")
    with node.connect(db="custom") as c:
        assert c.safe_sql("SELECT provider_name, key_name FROM vault.pg_tde_key_info()") == [
            ["global-provider", "custom-key"]
        ]
        assert c.sql_value("SELECT id FROM enc_t") == "99"
        assert c.sql_value("SELECT vault.pg_tde_is_encrypted('enc_t')") == "t"


def exercise_rich(node):
    # writes through the upgraded catalog: constraints, sequences, new relations
    node.safe_sql("DELETE FROM parent_t WHERE id = 1")
    assert node.safe_sql("SELECT id FROM child_t") == [["12"]]
    assert node.sql_value("INSERT INTO orders (amount) VALUES (99) RETURNING id") == "1300"
    node.expect_error(r'violates check constraint "orders_amount_check"', "INSERT INTO orders (amount) VALUES (-1)")
    node.safe_sql("""
        CREATE TABLE post_t (id int) USING tde_heap;
        INSERT INTO post_t VALUES (1);
        INSERT INTO part_t VALUES (5, '2025-12-31');
    """)
    _encrypted(node, "post_t")
    assert node.sql_value("SELECT count(*) FROM part_t_2025") == "3"
