import pytest

from pgtde import api
from pgtde.checks import check_tde_heap


def test_switch_cipher_to_aes_256(tde_node_db):
    node = tde_node_db
    node.safe_sql("CREATE TABLE test_enc0 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap")
    node.safe_sql("INSERT INTO test_enc0 (k) VALUES ('multitude'), ('multitudinous')")
    rows = [["1", "multitude"], ["2", "multitudinous"]]
    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == rows

    node.db.add_config({"pg_tde.cipher": "aes_256"})
    node.restart()

    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == rows
    node.safe_sql("INSERT INTO test_enc0 (k) VALUES ('multitudinously'), ('multitudinousness')")
    assert node.safe_sql("SELECT * FROM test_enc0 ORDER BY id") == [
        *rows,
        ["3", "multitudinously"],
        ["4", "multitudinousness"],
    ]

    check_tde_heap(node)


def test_cipher_guc(tde_node):
    node = tde_node
    assert node.sql_value("SHOW pg_tde.cipher") == "aes_128"
    node.expect_error(r'invalid value for parameter "pg_tde\.cipher": "aes_999"', "SET pg_tde.cipher = 'aes_999'")
    assert node.sql_value("SHOW pg_tde.cipher") == "aes_128"


CTX_SETUP = """
    CREATE TABLE ctx_a (id int PRIMARY KEY, payload text NOT NULL) USING tde_heap;
    CREATE TABLE ctx_b (id int PRIMARY KEY, payload text NOT NULL) USING tde_heap;
    INSERT INTO ctx_a SELECT i, repeat(md5(i::text), 8) FROM generate_series(1, 20000) i;
    INSERT INTO ctx_b SELECT i, repeat(md5((i + 100000)::text), 8) FROM generate_series(1, 10000) i;
    UPDATE ctx_a SET payload = repeat('Z', 128) WHERE id % 1009 = 0;
    UPDATE ctx_b SET payload = repeat('Q', 128) WHERE id % 1013 = 0;
    DELETE FROM ctx_a WHERE id % 4001 = 0;
    DELETE FROM ctx_b WHERE id % 4003 = 0;

    CREATE TABLE ctx_part (k int NOT NULL, v text NOT NULL, PRIMARY KEY (k)) PARTITION BY RANGE (k);
    CREATE TABLE ctx_part_1 PARTITION OF ctx_part FOR VALUES FROM (MINVALUE) TO (5000) USING tde_heap;
    CREATE TABLE ctx_part_2 PARTITION OF ctx_part FOR VALUES FROM (5000) TO (10000) USING tde_heap;
    CREATE TABLE ctx_part_3 PARTITION OF ctx_part FOR VALUES FROM (10000) TO (MAXVALUE) USING tde_heap;
    INSERT INTO ctx_part SELECT i, repeat(md5(i::text), 6) FROM generate_series(1, 12000) i;

    CREATE TABLE ctx_toast (id int PRIMARY KEY, blob text STORAGE EXTERNAL NOT NULL) USING tde_heap;
    INSERT INTO ctx_toast SELECT i, repeat(chr(65 + i % 26), 12000) FROM generate_series(1, 250) i;

    CREATE TABLE ctx_ctas USING tde_heap AS SELECT id, payload FROM ctx_a WHERE id <= 500;
    ALTER TABLE ctx_ctas ADD PRIMARY KEY (id);

    CREATE TABLE ctx_trunc (n int PRIMARY KEY, note text NOT NULL) USING tde_heap;
    INSERT INTO ctx_trunc SELECT g, repeat('n', 72) FROM generate_series(1, 9000) g;

    CREATE TABLE ctx_copy (id int PRIMARY KEY, v text NOT NULL) USING tde_heap;
"""

INTERLEAVE = """
    DO $$ BEGIN
      FOR _pass IN 1..10 LOOP
        PERFORM count(*) FROM ctx_a WHERE id % 97 = 0;
        PERFORM sum(length(payload)) FROM ctx_b WHERE id % 89 = 0;
        PERFORM sum(length(blob)) FROM ctx_toast WHERE id % 11 <> 0;
        PERFORM count(*) FROM ctx_part WHERE k % 13 = 0;
      END LOOP;
    END $$
"""

ENCRYPTED = [
    "ctx_a",
    "ctx_b",
    "ctx_a_pkey",
    "ctx_b_pkey",
    "ctx_part_1",
    "ctx_part_2",
    "ctx_part_3",
    "ctx_part_1_pkey",
    "ctx_part_2_pkey",
    "ctx_part_3_pkey",
    "ctx_toast",
    "ctx_ctas",
    "ctx_ctas_pkey",
    "ctx_trunc",
    "ctx_copy",
]

CHECKS = [
    ("SELECT bool_and(payload = repeat(md5(id::text), 8)) FROM ctx_a WHERE id IN (1, 2, 7, 9000, 19999)", "t"),
    ("SELECT bool_and(payload = repeat(md5((id + 100000)::text), 8)) FROM ctx_b WHERE id IN (1, 2, 7, 9999)", "t"),
    ("SELECT payload = repeat('Z', 128) FROM ctx_a WHERE id = 1009", "t"),
    ("SELECT payload = repeat('Q', 128) FROM ctx_b WHERE id = 1013", "t"),
    ("SELECT count(*) FROM ctx_a WHERE id IN (4001, 8002)", "0"),
    ("SELECT count(*) FROM ctx_b WHERE id = 4003", "0"),
    ("SELECT count(*) || ',' || sum(k) FROM ctx_part", "12000,72006000"),
    ("SELECT bool_and(v = repeat(md5(k::text), 6)) FROM ctx_part WHERE k IN (1, 4999, 5000, 9999, 10000, 12000)", "t"),
    ("SELECT count(*) FROM ctx_toast WHERE blob = repeat(chr(65 + id % 26), 12000)", "250"),
    ("SELECT count(*) FROM ctx_ctas", "500"),
    ("SELECT bool_and(payload = repeat(md5(id::text), 8)) FROM ctx_ctas WHERE id IN (1, 250, 500)", "t"),
    ("SELECT n || ',' || note FROM ctx_trunc", "7,trunc-reload"),
    ("SELECT count(*) FROM ctx_copy WHERE v = 'copy-payload-' || id", "2000"),
]

SNAPSHOT = """
    SELECT 'a', count(*), sum(id::bigint), sum(length(payload)) FROM ctx_a UNION ALL
    SELECT 'b', count(*), sum(id::bigint), sum(length(payload)) FROM ctx_b UNION ALL
    SELECT 'part', count(*), sum(k::bigint), sum(length(v)) FROM ctx_part UNION ALL
    SELECT 'toast', count(*), sum(id::bigint), sum(length(blob)) FROM ctx_toast UNION ALL
    SELECT 'ctas', count(*), sum(id::bigint), sum(length(payload)) FROM ctx_ctas UNION ALL
    SELECT 'trunc', count(*), sum(n::bigint), sum(length(note)) FROM ctx_trunc UNION ALL
    SELECT 'copy', count(*), sum(id::bigint), sum(length(v)) FROM ctx_copy
"""


def _filenode(node, rel):
    return node.sql_value(f"SELECT pg_relation_filenode('{rel}')")


BLKS_READ = "SELECT heap_blks_read FROM pg_statio_user_tables WHERE relname = 'ctx_a'"


def _verify(node):
    for rel in ENCRYPTED:
        assert api.is_encrypted(node, rel) is True, rel
    toast = node.sql_value("SELECT reltoastrelid::regclass::text FROM pg_class WHERE relname = 'ctx_toast'")
    assert api.is_encrypted(node, toast) is True
    assert node.sql_value(f"SELECT pg_relation_size('{toast}') > 0") == "t"
    for sql, want in CHECKS:
        assert node.sql_value(sql) == want, sql
    return node.safe_sql(SNAPSHOT)


# shared_buffers small so scans read and decrypt through the SMGR, not the
# buffer cache
@pytest.mark.bug("PG-2278")
@pytest.mark.node_config({"shared_buffers": "2MB"})
def test_cipher_context_reuse(tde_node_db, cipher, tmp_path):
    node = tde_node_db
    assert node.sql_value("SHOW pg_tde.cipher") == cipher
    node.safe_sql(CTX_SETUP)
    node.safe_sql("VACUUM ctx_a, ctx_b")
    node.safe_sql(INTERLEAVE)

    node.safe_sql("""
        BEGIN;
        SAVEPOINT sp;
        UPDATE ctx_ctas SET payload = repeat('!', 128) WHERE id <= 250;
        ROLLBACK TO SAVEPOINT sp;
        COMMIT;
    """)

    before = _filenode(node, "ctx_trunc")
    node.safe_sql("TRUNCATE ctx_trunc")
    assert _filenode(node, "ctx_trunc") != before
    node.safe_sql("INSERT INTO ctx_trunc VALUES (7, 'trunc-reload')")

    before = {r: _filenode(node, r) for r in ("ctx_b", "ctx_b_pkey")}
    node.safe_sql("REINDEX TABLE ctx_b")
    node.safe_sql("CLUSTER ctx_b USING ctx_b_pkey")
    assert all(_filenode(node, r) != f for r, f in before.items())

    copy_file = tmp_path / "ctx_copy.tsv"
    copy_file.write_text("".join(f"{i}\tcopy-payload-{i}\n" for i in range(1, 2001)))
    node.safe_sql(f"COPY ctx_copy FROM '{copy_file}'")
    node.safe_sql("ANALYZE")

    # cold reads go through the SMGR decrypt path
    node.safe_sql("CHECKPOINT")
    read_before = node.sql_value(BLKS_READ)
    assert node.sql_value("SELECT count(*) FROM ctx_a") == "19996"
    node.safe_sql("SELECT pg_stat_force_next_flush()")
    node.poll_until(f"SELECT ({BLKS_READ}) > {read_before}", timeout=10)

    with node.connect() as conn:
        conn.safe_sql("SET enable_seqscan = off")
        conn.safe_sql("SET enable_bitmapscan = off")
        query = "SELECT count(*) || ',' || max(length(payload)) FROM ctx_a WHERE id BETWEEN 100 AND 200"
        plan = "\n".join(r[0] for r in conn.safe_sql(f"EXPLAIN {query}"))
        assert "Index Scan using ctx_a_pkey" in plan, plan
        assert conn.sql_value(query) == "101,256"

    union = """
        SELECT sum(cnt) FROM (
            SELECT count(*) AS cnt FROM ctx_part WHERE k % 3 = 0 UNION ALL
            SELECT count(*) FROM ctx_toast WHERE id % 5 = 0 UNION ALL
            SELECT count(*) FROM ctx_ctas WHERE id % 7 = 0 UNION ALL
            SELECT count(*) FROM ctx_trunc UNION ALL
            SELECT count(*) FROM ctx_a WHERE id % 17 = 0 UNION ALL
            SELECT count(*) FROM ctx_b WHERE id % 19 = 0
        ) q
    """
    # 4000 + 50 + 71 + 1 + 1176 + 526
    total = "5824"
    assert node.sql_value(union) == total

    snapshot = _verify(node)
    node.restart()
    assert _verify(node) == snapshot
    assert node.sql_value(union) == total
