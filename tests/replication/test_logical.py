import pytest

from pgtde.wal import wal_contains

MARKER = "logical-marker"


def _node(factory, keyring, name, wal_encrypt):
    node = factory(name, config={"wal_level": "logical"})
    node.setup_db_key(keyring, key=f"{name}-db-key")
    if wal_encrypt:
        node.setup_server_key(keyring, key=f"{name}-server-key", wal_encrypt=True)
        node.restart()
    return node


def _expected():
    rows = {i: f"{MARKER}{i}" for i in range(1, 501)}
    rows |= {i: f"{MARKER}-post{i}" for i in range(501, 1001)}
    for i in range(1, 11):
        rows[i] += "-upd"
    for i in range(11, 21):
        del rows[i]
    return [[str(k), v] for k, v in sorted(rows.items())]


@pytest.mark.parametrize("wal_encrypt", [False, True], ids=["wal_plain", "wal_encrypted"])
@pytest.mark.parametrize("sub_am", ["heap", "tde_heap"])
def test_logical_replication(tde_node_factory, keyring_obj, sub_am, wal_encrypt):
    pub = _node(tde_node_factory, keyring_obj, "pub", wal_encrypt)
    sub = _node(tde_node_factory, keyring_obj, "sub", wal_encrypt)
    pub.safe_sql("CREATE TABLE logical_src (id int PRIMARY KEY, val text) USING tde_heap")
    sub.safe_sql(f"CREATE TABLE logical_src (id int PRIMARY KEY, val text) USING {sub_am}")
    pub.safe_sql(f"INSERT INTO logical_src SELECT i, '{MARKER}' || i FROM generate_series(1, 500) i")
    pub.safe_sql("CREATE PUBLICATION tde_pub FOR TABLE logical_src")
    conninfo = f"host=localhost port={pub.port} dbname=postgres"
    sub.safe_sql(f"CREATE SUBSCRIPTION tde_sub CONNECTION '{conninfo}' PUBLICATION tde_pub")

    sub.poll_until("SELECT bool_and(srsubstate = 'r') FROM pg_subscription_rel", "t")
    assert sub.safe_sql("SELECT count(*), sum(id) FROM logical_src") == [["500", "125250"]]

    # decoded from WAL, not the initial COPY
    pub.safe_sql(f"INSERT INTO logical_src SELECT i, '{MARKER}-post' || i FROM generate_series(501, 1000) i")
    pub.safe_sql("UPDATE logical_src SET val = val || '-upd' WHERE id <= 10")
    pub.safe_sql("DELETE FROM logical_src WHERE id BETWEEN 11 AND 20")
    lsn = pub.sql_value("SELECT pg_current_wal_lsn()")
    caught_up = """
        SELECT coalesce(bool_or(replay_lsn >= $1::pg_lsn AND state = 'streaming'), false)
        FROM pg_stat_replication WHERE application_name = 'tde_sub'
    """
    pub.poll_until(caught_up, "t", (lsn,))

    assert sub.safe_sql("SELECT id, val FROM logical_src ORDER BY id") == _expected()
    assert pub.is_encrypted("logical_src") is True
    assert sub.is_encrypted("logical_src") is (sub_am == "tde_heap")
    sub.safe_sql("CHECKPOINT")
    if sub_am == "tde_heap":
        sub.assert_not_on_disk("logical_src", MARKER)
    else:
        sub.assert_on_disk("logical_src", MARKER)

    if wal_encrypt:
        assert not wal_contains(pub, MARKER)
        assert not wal_contains(sub, MARKER)
    else:
        assert wal_contains(sub, MARKER)
