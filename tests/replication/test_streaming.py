import hashlib

import pytest

from pgtde import api
from pgtde.node import TdeNode


@pytest.mark.node_config({"checkpoint_timeout": "1h"})
def test_streaming_replication(tde_node, keyring_obj):
    primary = tde_node
    with TdeNode.from_backup(primary.basebackup(), primary, name="replica") as replica:
        primary.setup_db_key(keyring_obj, provider="db-provider", key="test-key")
        primary.safe_sql("""
            CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
            INSERT INTO test_enc (x) VALUES (1), (2);
            CREATE TABLE test_plain (x int PRIMARY KEY) USING heap;
            INSERT INTO test_plain (x) VALUES (3), (4);
        """)

        primary.wait_for_catchup(replica)

        assert replica.is_encrypted("test_enc") is True
        assert replica.is_encrypted("test_enc_pkey") is True
        assert replica.safe_sql("SELECT * FROM test_enc ORDER BY x") == [["1"], ["2"]]
        assert replica.is_encrypted("test_plain") is False
        assert replica.is_encrypted("test_plain_pkey") is False
        assert replica.safe_sql("SELECT * FROM test_plain ORDER BY x") == [["3"], ["4"]]

        # primary crash with WAL encryption, standby keeps plain WAL
        primary.setup_server_key(keyring_obj, provider="global-provider", key="test-global-key")
        primary.safe_sql("""
            CREATE TABLE test_enc2 (x int PRIMARY KEY) USING tde_heap;
            INSERT INTO test_enc2 (x) VALUES (1), (2);
        """)
        primary.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = 'on'")

        primary.kill()
        primary.poll_start()
        assert primary.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        assert replica.sql_value("SHOW pg_tde.wal_encrypt") == "off"
        primary.wait_for_catchup(replica)

        assert replica.safe_sql("SELECT * FROM test_enc2 ORDER BY x") == [["1"], ["2"]]

        primary.safe_sql("""
            INSERT INTO test_enc2 (x) SELECT generate_series(3, 1000);
            INSERT INTO test_plain (x) SELECT generate_series(5, 1000);
        """)
        primary.wait_for_catchup(replica)

        assert replica.safe_sql("SELECT count(*), sum(x) FROM test_enc2") == [["1000", "500500"]]
        assert replica.safe_sql("SELECT count(*), sum(x) FROM test_plain") == [["998", "500497"]]


def test_standby_follows_key_rotation(tde_node, keyring_obj):
    primary = tde_node
    primary.setup_server_key(keyring_obj, key="server-key-1", wal_encrypt=True)
    api.create_key(primary, "db-key-1", "global-provider", scope="global")
    api.set_key(primary, "db-key-1", "global-provider", scope="global")
    primary.restart()
    primary.safe_sql("""
        CREATE TABLE pre_rotation (id int PRIMARY KEY) USING tde_heap;
        INSERT INTO pre_rotation SELECT generate_series(1, 500);
    """)
    with TdeNode.from_backup(primary.tde_basebackup(), primary, name="standby") as standby:
        assert primary.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        assert standby.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        api.create_key(primary, "server-key-2", "global-provider", scope="global")
        api.set_server_key(primary, "server-key-2", "global-provider")
        api.create_key(primary, "db-key-2", "global-provider", scope="global")
        api.set_key(primary, "db-key-2", "global-provider", scope="global")
        primary.safe_sql("""
            INSERT INTO pre_rotation SELECT generate_series(501, 1000);
            CREATE TABLE post_rotation (id int PRIMARY KEY) USING tde_heap;
            INSERT INTO post_rotation SELECT generate_series(1, 100);
        """)
        primary.wait_for_catchup(standby)

        assert api.server_key_info(standby)[1:] == ["global-provider", "server-key-2"]
        assert api.key_info(standby)[1:] == ["global-provider", "db-key-2"]
        assert standby.is_encrypted("post_rotation") is True
        expected = [["1000", "500500", "100", "5050"]]
        query = """
            SELECT * FROM (SELECT count(*), sum(id) FROM pre_rotation), (SELECT count(*), sum(id) FROM post_rotation)
        """
        assert standby.safe_sql(query) == expected
        # keys and WAL read back from disk, not from the redo cache
        standby.restart()
        assert standby.safe_sql(query) == expected


def test_standby_replays_dml_on_encrypted_table(tde_node_db):
    primary = tde_node_db
    with TdeNode.from_backup(primary.basebackup(), primary, name="standby") as standby:
        primary.safe_sql("CREATE TABLE dml_load (id bigserial PRIMARY KEY, data text) USING tde_heap")
        primary.safe_sql("INSERT INTO dml_load (data) SELECT md5(i::text) FROM generate_series(1, 50000) i")
        primary.safe_sql("UPDATE dml_load SET data = 'updated' WHERE id % 2 = 0")
        primary.safe_sql("DELETE FROM dml_load WHERE id % 10 = 0")
        primary.wait_for_catchup(standby)

        assert standby.is_encrypted("dml_load") is True
        assert standby.is_encrypted("dml_load_pkey") is True
        assert standby.safe_sql("SELECT count(*), count(*) FILTER (WHERE data = 'updated'), sum(id) FROM dml_load") == [
            ["45000", "20000", "1125000000"]
        ]
        assert standby.safe_sql("SELECT id, data FROM dml_load WHERE id IN (3, 4, 10) ORDER BY id") == [
            ["3", hashlib.md5(b"3").hexdigest()],
            ["4", "updated"],
        ]


# small buffers and no FPW widen the race window
@pytest.mark.node_config({"full_page_writes": "off", "shared_buffers": "1MB"})
@pytest.mark.bug("PG-2861")
@pytest.mark.xfail(
    strict=False,
    reason="PG-2861: set_default_key races walsender server-key fallback, standby FATALs replaying ROTATE for db 1664",
)
def test_standby_follows_default_key_setup(tde_node, keyring_obj):
    node = tde_node
    with TdeNode.from_backup(node.basebackup(), node, name="standby") as standby:
        node.setup_default_key(keyring_obj, provider="global-keyring", key="default-key")
        # key functions do not flush their WAL, a commit does
        node.safe_sql("CREATE TABLE flush_wal (a int)")
        node.wait_for_catchup(standby)
        assert api.default_key_info(standby)[1:] == ["global-keyring", "default-key"]
