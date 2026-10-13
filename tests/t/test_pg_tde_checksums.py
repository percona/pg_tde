import re

import stormweaver.testing as st

from pgtde.node import TdeNode


def test_pg_tde_checksums(pg_install_dir, sw_log_dir, pg_major, file_keyring):
    # checksums are on by default only from 18
    initdb_args = ["--no-data-checksums"] if pg_major >= 18 else []
    with TdeNode.fresh(pg_install_dir, name="checksums", initdb_args=initdb_args) as node:
        node.setup_db_key(file_keyring, provider="db", key="server-key")
        node.safe_sql("CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap")
        node.safe_sql("INSERT INTO test_enc (k) VALUES (1), (2)")
        relfile = node.relation_filepath("test_enc")
        node.stop()

        st.command_ok(
            node.tool("pg_tde_checksums", "--no-sync", "--enable", node.datadir),
            "can enable checksums for encrypted tables",
        )

        node.start()
        assert node.safe_sql("SELECT * FROM test_enc") == [["1"], ["2"]]
        node.stop()

        st.corrupt_page_checksum(relfile, 0)

        cp = node.tool("pg_tde_checksums", "--check", node.datadir)
        assert cp.returncode == 1, cp.stdout + cp.stderr
        assert re.search(r"Bad checksums:.*1", cp.stdout), cp.stdout
        assert re.search(r"checksum verification failed", cp.stderr), cp.stderr

        node.start()
        node.expect_error(r"invalid page in block 0 of relation", "SELECT * FROM test_enc")
