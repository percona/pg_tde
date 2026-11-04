import pytest

from pgtde import api


@pytest.mark.node_config({"checkpoint_timeout": "1h"})
def test_crash_recovery(tde_node, keyring_obj):
    node = tde_node
    node.setup_server_key(keyring_obj, provider="global_keyring", key="wal_encryption_key")
    node.setup_db_key(keyring_obj, provider="db_keyring", key="db_key")
    node.safe_sql("""
        CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
        INSERT INTO test_enc (x) VALUES (1), (2);
        CREATE TABLE test_plain (x int PRIMARY KEY) USING heap;
        INSERT INTO test_plain (x) VALUES (3), (4);
    """)
    api.set_wal_encrypt(node, True)

    node.kill()
    # crash recovery of the pg_tde setup
    node.poll_start()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"

    def rotate(n):
        wal_key = f"wal_encryption_key_{n}"
        api.create_key(node, wal_key, "global_keyring", scope="global")
        api.set_server_key(node, wal_key, "global_keyring")
        api.create_key(node, f"db_key_{n}", "db_keyring")
        api.set_key(node, f"db_key_{n}", "db_keyring")

    rotate(1)
    node.safe_sql("INSERT INTO test_enc (x) VALUES (3), (4)")

    node.kill()
    # save_principal_key redo must not destroy a WAL key created at start
    node.poll_start()

    rotate(2)
    node.safe_sql("INSERT INTO test_enc (x) VALUES (5), (6)")

    node.kill()
    # key rotation must not destroy a WAL key created at start
    node.poll_start()

    assert node.safe_sql("TABLE test_enc") == [[str(i)] for i in range(1, 7)]

    node.safe_sql("CREATE TABLE test_enc2 (x int PRIMARY KEY) USING tde_heap")

    node.kill()
    # redo of smgr internal key creation with the key on disk
    node.poll_start()

    node.safe_sql("INSERT INTO test_enc (x) VALUES (7), (8)")

    node.kill()
    # redo when cipher changed after the crash
    node.db.add_config({"pg_tde.cipher": "aes_256"})
    node.poll_start()

    assert node.safe_sql("TABLE test_enc") == [[str(i)] for i in range(1, 9)]

    # unlogged init forks of regular relations are empty, a sequence is
    # needed to catch WAL replay overwriting the init fork key
    node.safe_sql("""
        CREATE UNLOGGED SEQUENCE seq_unlogged OWNED BY test_enc.x;
        SELECT nextval('seq_unlogged');
        SELECT nextval('seq_unlogged');
    """)
    assert node.is_encrypted("seq_unlogged") is True

    node.kill()
    node.poll_start()

    assert node.sql_value("SELECT nextval('seq_unlogged')") == "1"
