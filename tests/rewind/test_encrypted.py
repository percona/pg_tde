import re

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.checks import check_tde_heap, setup_error
from pgtde.rewind import (
    ALL_MODES,
    check_asymmetric_tables,
    check_tail_block,
    create_asymmetric_tables,
    create_tail_block,
    diverge_tail_block,
)
from pgtde.wal import archive_all, archive_config, wal_contains

PROVIDER = "wal-provider"


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
        s.safe_sql("VACUUM tbl1")
        # changed blocks on the old primary are copied back, their forks too
        p.safe_sql("UPDATE tbl1 SET f1 = 'P' WHERE id % 11 = 0")
        p.safe_sql("CHECKPOINT")

        rw.run_rewind(mode)

        assert p.sql_value("SELECT count(*) FROM tbl1") == "1934"
        # replaying inserts reads the free space map
        s.safe_sql("INSERT INTO tbl1 (f1) SELECT repeat('post', 100) FROM generate_series(1, 100)")
        s.wait_for_catchup(p)
        assert p.sql_value("SELECT count(*) FROM tbl1") == "2034"
        assert "; zeroing out page" not in p.log_since(log_start)


# pg_tde_rewind restores the target WAL segments recycled since the divergence
# from the archive and keeps those recovery needs; they must be re-encrypted
# with the source's keys, so no "invalid magic number".
@pytest.mark.bug("PG-2397")
@pytest.mark.bug("PG-2407")
@pytest.mark.parametrize("source", ["local", "remote"])
def test_keep_archive_wal(source, cipher, pg_install_dir, file_rewind_driver, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    config = {
        "wal_keep_size": "0",
        **archive_config(f"{pg_install_dir}/bin", archive, restore=True),
    }
    with file_rewind_driver(cipher, config=config) as rw:
        p = rw.setup_primary()
        log_start = p.log_offset()

        p.safe_sql("CREATE TABLE t1(id int) USING tde_heap; INSERT INTO t1 SELECT generate_series(1,10000);")
        archive_all(p)
        p.safe_sql("CHECKPOINT")

        s = rw.create_standby()

        archive_all(p)
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        s.safe_sql("INSERT INTO t1 VALUES (999999)")
        archive_all(s)
        s.safe_sql("CHECKPOINT")

        api.create_key(s, "key_after_promotion", PROVIDER, scope="global")
        api.set_server_key(s, "key_after_promotion", PROVIDER)
        s.safe_sql("SELECT pg_switch_wal()")

        create_asymmetric_tables(p, s)

        for i in range(6):
            p.safe_sql(f"INSERT INTO t1 SELECT generate_series({100000 + i * 1000}, {100999 + i * 1000})")
            p.safe_sql("CHECKPOINT")
            p.safe_sql("SELECT pg_switch_wal()")

        archive_all(p)
        p.safe_sql("CHECKPOINT")

        archive_all(s)
        s.safe_sql("CHECKPOINT")

        p.stop()
        with p.db.preserve_config() as conf:
            if source == "local":
                s.stop()
            cp = rw.rewind(source=source, restore=True, config_file=conf)
            st.command_ok(cp, f"pg_rewind {source}")
        restored = set(re.findall(r'using file ".*/(\w{24})" restored from archive', cp.stderr))
        needed = set(re.findall(r'Not removing file "pg_wal/(\w{24})" because it is required for recovery', cp.stderr))
        assert restored & needed, cp.stderr
        # readable with the keys the rewound node starts with
        for seg in sorted(restored & needed):
            dump = p.tool("pg_tde_waldump", "-k", p.datadir / "pg_tde", "-p", p.datadir / "pg_wal", seg)
            assert "invalid magic number" not in dump.stderr, dump.stderr
            assert re.search(r"^rmgr: ", dump.stdout, re.M), dump.stderr

        # not a standalone start: like plain pg_rewind it would replay the
        # restored segments of the old timeline
        if source == "local":
            s.start()
        p.rejoin_as_standby(s)
        s.wait_for_catchup(p)

        log = p.log_since(log_start)
        assert "invalid magic number" not in log
        assert "WAL ends before consistent recovery point" not in log
        assert p.sql_value("SELECT count(*) FROM t1") == "10001"
        check_asymmetric_tables(p)


# pg_tde_rewind keeps some WAL segments on the target; restore_command makes
# new WAL keys while the replica is created, so kept segments must be
# re-encrypted. The new primary also switches to a new server and principal key.
@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_keep_wal_seg(mode, cipher, pg_install_dir, file_rewind_driver, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    config = {
        "wal_level": "replica",
        **archive_config(f"{pg_install_dir}/bin", archive, restore=True),
    }
    with file_rewind_driver(cipher, config=config) as rw:
        p = rw.setup_primary()
        p.restart()
        create_tail_block(p)
        s = rw.create_standby()
        rw.promote_standby()
        api.create_key(s, "rotated-key", PROVIDER, scope="global")
        api.set_server_key(s, "rotated-key", PROVIDER)
        api.set_key(s, "rotated-key", PROVIDER, scope="global")
        diverge_tail_block(p, s)
        rw.run_rewind(mode)
        check_tail_block(p)
        assert api.server_key_info(p)[1:] == [PROVIDER, "rotated-key"]
        assert api.key_info(p)[1:] == [PROVIDER, "rotated-key"]
        # the rewound node keeps replaying past its kept segments
        s.safe_sql("INSERT INTO tail_t (f1) SELECT 'after-rewind' FROM generate_series(1, 300)")
        s.wait_for_catchup(p)
        assert p.sql_value("SELECT count(*) FROM tail_t WHERE f1 = 'after-rewind'") == "300"


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


# The rewound node takes over as primary: its WAL stays encrypted, its
# sequence continues past the values handed out by the source, and its
# relations survive rewrites and restarts.
def test_rewound_node_promotes(file_rewind_driver):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("""
            CREATE SEQUENCE ha_seq;
            CREATE TABLE ha_t (id int DEFAULT nextval('ha_seq') PRIMARY KEY, v text);
            INSERT INTO ha_t (v) SELECT 'base' FROM generate_series(1, 1000);
        """)
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        s.safe_sql("INSERT INTO ha_t (v) SELECT 'source' FROM generate_series(1, 500)")
        s.safe_sql("DELETE FROM ha_t WHERE id % 3 = 0")
        p.safe_sql("INSERT INTO ha_t (v) SELECT 'target' FROM generate_series(1, 700)")

        rw.run_rewind("local")

        s.stop()
        p.promote()
        p.poll_until("SELECT NOT pg_is_in_recovery()")
        assert p.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        # a sequence gone back before the source's rows hits the primary key
        p.safe_sql("INSERT INTO ha_t (v) SELECT 'promoted-row-marker' FROM generate_series(1, 100)")
        assert not wal_contains(p, "promoted-row-marker")
        with p.connect() as c:
            c.safe_sql("SET enable_seqscan = off")
            assert c.sql_value("SELECT count(*) FROM ha_t WHERE id > 0") == "1100"
        p.safe_sql("REINDEX TABLE ha_t")
        p.safe_sql("VACUUM FULL ha_t")
        p.restart()
        p.restart()
        assert p.safe_sql("SELECT v, count(*) FROM ha_t GROUP BY v ORDER BY v") == [
            ["base", "667"],
            ["promoted-row-marker", "100"],
            ["source", "333"],
        ]
        assert p.is_encrypted("ha_t")
        check_tde_heap(p)


# The old primary crashed before the promotion, pg_tde_rewind runs its crash
# recovery first. The rewound node must come up again after a clean stop.
def test_rewind_after_target_crash(file_rewind_driver):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE crash_t (id int); INSERT INTO crash_t VALUES (1)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        p.safe_sql("INSERT INTO crash_t VALUES (2)")
        p.wait_for_catchup(s)
        p.stop(mode="immediate")
        s.promote()
        s.poll_until("SELECT NOT pg_is_in_recovery()")
        s.safe_sql("INSERT INTO crash_t VALUES (3)")

        # the stop in run_rewind finds the old primary already down
        rw.run_rewind("local")

        assert p.sql_value("SELECT string_agg(id::text, ',' ORDER BY id) FROM crash_t") == "1,2,3"
        p.restart()
        s.safe_sql("INSERT INTO crash_t VALUES (4)")
        s.wait_for_catchup(p)
        assert p.sql_value("SELECT string_agg(id::text, ',' ORDER BY id) FROM crash_t") == "1,2,3,4"


# A relation created after the standby grows past one 1 GiB segment; the old
# primary changes blocks in both segments, so pg_tde_rewind re-encrypts copied
# blocks of every segment with the relation's key.
@pytest.mark.slow
@pytest.mark.bug("PG-2876")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="PG-2876: pg_tde_rewind uses wrong source key for relation segments after the first",
)
def test_rewind_multisegment_relation(file_rewind_driver):
    rows = 600_000
    # the standby replays 1 GiB, the primary must not recycle it first
    with file_rewind_driver(config={"wal_keep_size": "4GB"}) as rw:

        def setup():
            p = rw.setup_primary()
            s = rw.create_standby()
            p.safe_sql("""
                CREATE TABLE multi_seg (id int PRIMARY KEY, payload text);
                ALTER TABLE multi_seg ALTER COLUMN payload SET STORAGE PLAIN;
            """)
            p.safe_sql(
                f"INSERT INTO multi_seg SELECT g, rpad(g::text, 1800, md5(g::text)) FROM generate_series(1, {rows}) g"
            )
            # hint bits now, not as 1 GiB of full page images after the divergence
            p.safe_sql("VACUUM multi_seg")
            p.safe_sql("CHECKPOINT")
            assert p.relation_filepath("multi_seg").with_suffix(".1").exists()
            p.wait_for_catchup(s, timeout=600)
            rw.promote_standby()

            s.safe_sql(f"UPDATE multi_seg SET payload = 'S' WHERE id <= 100 OR id > {rows - 100}")
            s.safe_sql("CHECKPOINT")
            p.safe_sql(f"UPDATE multi_seg SET payload = 'P' WHERE id BETWEEN 200 AND 300 OR id > {rows - 1000}")
            p.safe_sql("CHECKPOINT")

            # run_rewind("local"), split so only the start of the rewound node may xfail
            p.stop(mode="immediate")
            with p.db.preserve_config() as conf:
                s.stop()
                st.command_ok(rw.rewind(config_file=conf), "pg_rewind local")
            s.start()
            return p, s

        p, s = setup_error(setup)
        off = p.log_offset()
        try:
            p.rejoin_as_standby(s)
        except RuntimeError as e:
            log = p.log_since(off)
            if "invalid page in block" not in log:
                raise
            raise AssertionError(f"rewound node does not start:\n{log[-3000:]}") from e
        s.wait_for_catchup(p)

        assert p.sql_value("SELECT count(*) FROM multi_seg") == str(rows)
        assert p.sql_value("SELECT count(*) FROM multi_seg WHERE payload = 'P'") == "0"
        assert p.sql_value("SELECT sum(length(payload)) FROM multi_seg") == str((rows - 200) * 1800 + 200)
