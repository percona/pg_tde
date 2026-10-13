import logging
import time

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.rewind import ALL_MODES, check_tail_block, create_tail_block, diverge_tail_block
from pgtde.wal import archive_config

PROVIDER = "wal-provider"

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


# Only changed blocks of the encrypted relation are copied from the source,
# mixing data encrypted with different keys; pg_tde_rewind must re-encrypt.
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_copy_blocks(mode, cipher, rewind_driver):
    with rewind_driver(cipher) as rw:
        p = rw.setup_primary()
        s = rw.create_standby()
        create_tail_block(p)
        rw.promote_standby()
        diverge_tail_block(p, s)
        rw.run_rewind(mode)
        check_tail_block(p)


# Encrypted relations in an external tablespace.
@pytest.mark.pg_min(17)
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_ext_tablespace(mode, cipher, rewind_driver, tmp_path):
    ts_primary = tmp_path / "ts1"
    ts_standby = tmp_path / "ts1_standby"
    ts_primary.mkdir()
    with rewind_driver(cipher) as rw:
        p = rw.setup_primary()
        p.safe_sql(f"CREATE TABLESPACE ts1 LOCATION '{ts_primary}'")
        s = rw.create_standby(f"--tablespace-mapping={ts_primary}={ts_standby}")
        create_tail_block(p, tablespace="ts1")
        rw.promote_standby()
        diverge_tail_block(p, s)
        rw.run_rewind(mode)
        check_tail_block(p)


# pg_tde_rewind re-encrypts FSM/VM fork blocks so the server does not zero
# them out on startup.
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_rewind_reencrypts_fsm_and_vm_forks(mode, cipher, rewind_driver):
    with rewind_driver(cipher) as rw:
        p = rw.setup_primary()
        log_start = p.log_offset()
        s = rw.create_standby()

        p.safe_sql("CREATE TABLE tbl1 (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap")
        p.safe_sql("INSERT INTO tbl1 (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        s.safe_sql("DELETE FROM tbl1 WHERE id % 15 = 0")
        s.safe_sql("INSERT INTO tbl1 (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)")

        rw.run_rewind(mode)

        with open(p.server_log, errors="replace") as f:
            f.seek(log_start)
            assert "; zeroing out page" not in f.read()
        assert p.sql_value("SELECT count(*) FROM tbl1") == "1934"


# pg_tde_rewind restores some target WAL segments from the archive and uses
# them for recovery after the rewind; they must be re-encrypted, so no
# "invalid magic number" in the server log.
def test_keep_archive_wal(pg_install_dir, rewind_driver, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    config = {
        "wal_keep_size": "0",
        "archive_timeout": "10s",
        **archive_config(f"{pg_install_dir}/bin", archive, restore=True),
    }
    with rewind_driver(config=config) as rw:
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


# pg_tde_rewind keeps some WAL segments on the target; restore_command makes
# new WAL keys while the replica is created, so kept segments must be
# re-encrypted.
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_keep_wal_seg(mode, cipher, pg_install_dir, rewind_driver, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    config = {
        "wal_level": "replica",
        **archive_config(f"{pg_install_dir}/bin", archive, restore=True),
    }
    with rewind_driver(cipher, config=config) as rw:
        p = rw.setup_primary()
        p.restart()
        create_tail_block(p)
        s = rw.create_standby()
        rw.promote_standby()
        diverge_tail_block(p, s)
        rw.run_rewind(mode)
        check_tail_block(p)


# The target's keys are preserved for unchanged and kept encrypted relations.
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_unchanged_rel(mode, cipher, rewind_driver):
    with rewind_driver(cipher) as rw:
        p = rw.setup_primary()
        s = rw.create_standby()

        p.safe_sql("CREATE TABLE tbl (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap")
        p.safe_sql("INSERT INTO tbl (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        # leaves the unchanged index files flushed on the source
        s.safe_sql("CHECKPOINT")

        rw.run_rewind(mode)

        assert p.sql_value("SELECT count(*) FROM tbl") == "1000"
