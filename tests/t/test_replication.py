from pgtde.node import TdeNode


def test_replication(pg_install_dir, sw_log_dir, tmp_path):
    with TdeNode.fresh(pg_install_dir, name="primary", config={"checkpoint_timeout": "1h"}) as primary:
        with TdeNode.from_backup(primary.basebackup(), primary, name="replica") as replica:
            primary.setup_db_key(tmp_path / "db.keys", provider="file-vault", key="test-key")
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

            # primary crash with WAL encryption
            # TODO: This does not seem to actually test WAL encryption
            primary.setup_server_key(tmp_path / "global.key", provider="file-vault", key="test-global-key")
            primary.safe_sql("""
                CREATE TABLE test_enc2 (x int PRIMARY KEY) USING tde_heap;
                INSERT INTO test_enc2 (x) VALUES (1), (2);
            """)
            primary.safe_sql("ALTER SYSTEM SET pg_tde.wal_encrypt = 'on'")

            primary.kill()
            primary.poll_start()
            primary.wait_for_catchup(replica)

            assert replica.safe_sql("SELECT * FROM test_enc2 ORDER BY x") == [["1"], ["2"]]
