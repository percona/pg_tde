# pg_tde_rewind restores some target WAL segments from the archive and uses
# them for recovery after the rewind; they must be re-encrypted, so no
# "invalid magic number" in the server log.
import logging
import time

import stormweaver.testing as st

from pgtde import api
from pgtde.rewind import TdeRewindDriver

PROVIDER = "file-keyring-wal"

log = logging.getLogger(__name__)


def wait_for_archive(archive, node, timeout=180):
    segment = node.sql_value("SELECT pg_walfile_name(pg_current_wal_lsn())")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (archive / segment).is_file():
            log.info("WAL archived: %s", segment)
            return
        time.sleep(1)
    raise TimeoutError(f"{segment} not archived after {timeout}s")


def test_pg_rewind_enc_keep_archive_wal(pg_install_dir, sw_log_dir, node_config, keyring_obj, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    decrypt = f"{pg_install_dir}/bin/pg_tde_archive_decrypt"
    encrypt = f"{pg_install_dir}/bin/pg_tde_restore_encrypt"
    config = {
        "wal_keep_size": "0",
        "archive_mode": "on",
        "archive_timeout": "10s",
        "archive_command": f'{decrypt} %f %p "cp %%p {archive}/%%f"',
        "restore_command": f'{encrypt} %f %p "cp {archive}/%%f %%p"',
    }
    with TdeRewindDriver(
        pg_install_dir, cipher="aes_128", keyring=keyring_obj, debug=True, config=node_config | config
    ) as rw:
        p = rw.setup_primary()
        log_start = p.log_offset()

        p.safe_sql("CREATE TABLE t1(id int) USING tde_heap; INSERT INTO t1 SELECT generate_series(1,10000);")
        p.safe_sql("CHECKPOINT")
        p.safe_sql("SELECT pg_switch_wal()")
        p.safe_sql("CHECKPOINT")
        wait_for_archive(archive, p)

        s = rw.create_standby()

        p.safe_sql("SELECT pg_switch_wal()")
        p.safe_sql("CHECKPOINT")
        wait_for_archive(archive, p)

        rw.promote_standby()

        s.safe_sql("INSERT INTO t1 VALUES (999999)")
        s.safe_sql("SELECT pg_switch_wal()")
        s.safe_sql("CHECKPOINT")
        wait_for_archive(archive, s)

        api.create_key(s, "key_after_promotion", PROVIDER, scope="global")
        api.set_server_key(s, "key_after_promotion", PROVIDER)
        s.safe_sql("SELECT pg_switch_wal()")

        s.safe_sql("CREATE TABLE target_only(id int) USING tde_heap; INSERT INTO target_only VALUES (1),(2);")
        p.safe_sql("CREATE TABLE source_only(id int) USING tde_heap; INSERT INTO source_only VALUES (10),(20);")

        p.safe_sql("SELECT pg_switch_wal()")
        p.safe_sql("CHECKPOINT")
        wait_for_archive(archive, p)

        s.safe_sql("SELECT pg_switch_wal()")
        s.safe_sql("CHECKPOINT")
        wait_for_archive(archive, s)

        p.stop()
        with p.db.preserve_config() as conf:
            s.stop()
            st.command_ok(
                p.tool(
                    rw.rewind_bin,
                    "--debug",
                    f"--source-pgdata={s.datadir}",
                    f"--target-pgdata={p.datadir}",
                    "--restore-target-wal",
                    f"--config-file={conf}",
                ),
                "pg_rewind local",
            )
        p.start()

        with open(p.server_log, errors="replace") as f:
            f.seek(log_start)
            assert "invalid magic number" not in f.read()
