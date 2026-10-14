import contextlib
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.node import TdeNode
from pgtde.pgbackrest import Stanza
from pgtde.standby import standby_from_backup_dir
from pgtde.wal import archive_all, wal_contains

pytestmark = pytest.mark.needs_pgbackrest

CONFIG = {"wal_level": "replica", "autovacuum": "off", "checkpoint_timeout": "1h", "wal_log_hints": "on"}
OPTIONS = {"start-fast": "y", "repo1-retention-full": "2", "compress-type": "none"}
# ciphertext WAL in the repo: pgBackRest cannot read the encrypted segment headers
RAW = {"archive-header-check": "n"}
CHECKSUMS = pytest.mark.node_config(initdb_args=["--data-checksums"])
IDS_SQL = "SELECT id FROM t ORDER BY id"


def _rotate(node, n):
    api.create_key(node, f"server-key-{n}", "global-provider", scope="global")
    api.set_server_key(node, f"server-key-{n}", "global-provider")
    api.create_key(node, f"db-key-{n}", "global-provider", scope="global")
    api.set_key(node, f"db-key-{n}", "global-provider", scope="global")


def _primary(factory, keyring, repo, *, decrypt=True, wal_encrypt=True, config=None, **options):
    node = factory("primary", config=CONFIG | (config or {}))
    stanza = Stanza(node, repo, decrypt=decrypt, **(OPTIONS | options))
    node.db.add_config(stanza.archive_config())
    node.setup_server_key(keyring, key="server-key-1", wal_encrypt=wal_encrypt)
    api.create_key(node, "db-key-1", "global-provider", scope="global")
    api.set_key(node, "db-key-1", "global-provider", scope="global")
    node.restart()
    stanza.create()
    return node, stanza


def _target(name="restored"):
    return Path(tempfile.mkdtemp(prefix="sw-backup-", dir="/tmp")) / name


def _adopt(pg_install, target, *, signal="recovery", config=None):
    # archive_mode off: a restored node must not push into the source's stanza
    return standby_from_backup_dir(
        target, pg_install.install_dir, name=target.name, config={"archive_mode": "off"} | (config or {}), signal=signal
    )


def _restored(stanza, pg_install, *extra):
    return _adopt(pg_install, stanza.restore(_target(), *extra))


def _labels(stanza):
    [info] = stanza.info()
    return {b["type"]: b["label"] for b in info["backup"]}


def _checksum_warnings(stanza):
    log = (stanza.repo / "log" / f"{stanza.name}-backup.log").read_text()
    return re.findall(r"WARN: invalid page checksums? found in file (\S+) at page", log)


def _case(id, decrypt=True, wal_encrypt=True, **options):
    return pytest.param(decrypt, wal_encrypt, options, id=id)


@CHECKSUMS
@pytest.mark.parametrize(
    ("decrypt", "wal_encrypt", "options"),
    [
        _case("decrypt"),
        _case("decrypt-wal-plain", wal_encrypt=False),
        _case("decrypt-lz4", compress_type="lz4"),
        _case("raw-async", decrypt=False, checksum_page="n", archive_async="y", **RAW),
        _case("raw-wal-plain", decrypt=False, wal_encrypt=False),
    ],
)
def test_backup_chain_restore(pg_install, tde_node_factory, keyring_obj, tmp_path, decrypt, wal_encrypt, options):
    primary, stanza = _primary(
        tde_node_factory, keyring_obj, tmp_path / "repo", decrypt=decrypt, wal_encrypt=wal_encrypt, **options
    )
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("CREATE TABLE p (id int PRIMARY KEY, v text) USING heap")
    primary.safe_sql("INSERT INTO t SELECT g, 'full' FROM generate_series(1, 100) g")
    primary.safe_sql("INSERT INTO p SELECT g, 'full' FROM generate_series(1, 100) g")
    primary.safe_sql("CREATE DATABASE app")
    with primary.connect(db="app") as conn:
        api.create_extension(conn)
        api.create_key(conn, "app-key", "global-provider", scope="global")
        api.set_key(conn, "app-key", "global-provider", scope="global")
        conn.safe_sql("CREATE TABLE a (id int PRIMARY KEY) USING tde_heap")
        conn.safe_sql("INSERT INTO a SELECT generate_series(1, 50)")
    primary.safe_sql("CHECKPOINT")
    stanza.backup("full")
    # one key generation per backup of the chain
    _rotate(primary, 2)
    primary.safe_sql("INSERT INTO t SELECT g, 'diff' FROM generate_series(101, 200) g")
    stanza.backup("diff")
    _rotate(primary, 3)
    primary.safe_sql("INSERT INTO t SELECT g, 'incr' FROM generate_series(201, 300) g")
    stanza.backup("incr")
    primary.safe_sql("INSERT INTO t VALUES (301, 'archived-only-marker')")
    assert wal_contains(primary, "archived-only-marker", flush=False) is not wal_encrypt
    archive_all(primary)
    stanza.check()

    labels = _labels(stanza)
    assert sorted(labels) == ["diff", "full", "incr"]
    if options.get("compress_type", "none") == "none":
        in_repo = any(b"archived-only-marker" in p.read_bytes() for p in stanza.archived_segments())
        assert in_repo == (decrypt or not wal_encrypt), "plaintext WAL in the repo"
    # pgBackRest verifies page checksums of the encrypted pages as plaintext
    warned = _checksum_warnings(stanza)
    if options.get("checksum_page") == "n":
        assert warned == []
    else:
        assert str(primary.relation_filepath("t")) in warned
        assert str(primary.relation_filepath("p")) not in warned

    # the full set first, the delta restore brings the chain and the new keys on top
    target = stanza.restore(_target(), f"--set={labels['full']}")
    stanza.restore(target, "--delta")
    with _adopt(pg_install, target) as node:
        node.start()
        node.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        assert node.safe_sql("SELECT v, count(*) FROM t GROUP BY v ORDER BY v") == [
            ["archived-only-marker", "1"],
            ["diff", "100"],
            ["full", "100"],
            ["incr", "100"],
        ]
        assert node.is_encrypted("t") is True
        assert node.is_encrypted("p") is False
        with node.connect(db="app") as conn:
            assert conn.safe_sql("SELECT count(*) FROM a") == [["50"]]
            assert api.is_encrypted(conn, "a") is True
            assert api.key_info(conn)[1:] == ["global-provider", "app-key"]
        assert api.key_info(node)[1:] == ["global-provider", "db-key-3"]
        assert api.server_key_info(node)[1:] == ["global-provider", "server-key-3"]
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == ("on" if wal_encrypt else "off")
        if wal_encrypt:
            node.safe_sql("INSERT INTO t VALUES (302, 'restored-node-marker')")
            assert not wal_contains(node, "restored-node-marker")


def _pitr(id, kind, *, decrypt=True, exclusive=False, action="promote", expected=(1, 2, 3)):
    return pytest.param(decrypt, kind, exclusive, action, [[str(i)] for i in expected], id=id)


@pytest.mark.parametrize(
    ("decrypt", "kind", "exclusive", "action", "expected"),
    [
        _pitr("decrypt-time", "time"),
        _pitr("decrypt-time-pause", "time", action="pause"),
        _pitr("decrypt-xid-exclusive", "xid", exclusive=True, expected=(1, 2)),
        _pitr("decrypt-immediate", "immediate", expected=(1, 2)),
        _pitr("raw-lsn-exclusive", "lsn", decrypt=False, exclusive=True),
    ],
)
def test_pitr_restore(pg_install, tde_node_factory, file_keyring, tmp_path, decrypt, kind, exclusive, action, expected):
    primary, stanza = _primary(
        tde_node_factory, file_keyring, tmp_path / "repo", decrypt=decrypt, **({} if decrypt else RAW)
    )
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO t VALUES (1, 'base')")
    primary.safe_sql("CREATE TABLE d (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO d VALUES (1, 'dropped-later')")
    primary.safe_sql("CREATE TABLE tr (id int PRIMARY KEY) USING tde_heap")
    primary.safe_sql("INSERT INTO tr SELECT generate_series(1, 100)")
    stanza.backup("full")
    primary.safe_sql("INSERT INTO t VALUES (2, 'incr')")
    stanza.backup("incr")

    # the rotation only exists in the archived WAL
    _rotate(primary, 2)
    primary.safe_sql("INSERT INTO t VALUES (3, 'target')")
    xid = primary.sql_value("SELECT xmin FROM t WHERE id = 3")
    # after commit 3, before commit 4
    [[lsn, ts]] = primary.safe_sql("SELECT pg_current_wal_lsn(), clock_timestamp()")
    primary.safe_sql("INSERT INTO t VALUES (4, 'after')")
    primary.safe_sql("UPDATE t SET v = 'changed' WHERE id = 1")
    primary.safe_sql("DELETE FROM t WHERE id = 2")
    primary.safe_sql("DROP TABLE d")
    primary.safe_sql("TRUNCATE tr")
    primary.safe_sql("INSERT INTO tr VALUES (999)")
    archive_all(primary)

    extra = [f"--type={kind}", f"--target-action={action}"]
    if kind != "immediate":
        extra.append(f"--target={ {'time': ts, 'lsn': lsn, 'xid': xid}[kind] }")
    if exclusive:
        extra.append("--target-exclusive")
    with _restored(stanza, pg_install, *extra) as node:
        node.start()
        if action == "pause":
            node.poll_until("SELECT pg_get_wal_replay_pause_state()", "paused", timeout=60)
            assert node.safe_sql(IDS_SQL) == expected
            node.safe_sql("SELECT pg_wal_replay_resume()")
        node.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        assert node.safe_sql(IDS_SQL) == expected
        assert node.sql_value("SELECT v FROM t WHERE id = 1") == "base"
        assert node.safe_sql("SELECT id, v FROM d") == [["1", "dropped-later"]]
        assert node.safe_sql("SELECT count(*), sum(id) FROM tr") == [["100", "5050"]]
        for rel in ("t", "d", "tr"):
            assert node.is_encrypted(rel) is True, rel
        # immediate stops at the end of the incr backup, before the rotation
        n = 1 if kind == "immediate" else 2
        assert api.key_info(node)[1:] == ["global-provider", f"db-key-{n}"]
        assert api.server_key_info(node)[1:] == ["global-provider", f"server-key-{n}"]
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"


def test_standby_restore_streams_from_primary(pg_install, tde_node_factory, file_keyring, tmp_path):
    primary, stanza = _primary(tde_node_factory, file_keyring, tmp_path / "repo")
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO t SELECT g, 'backup' FROM generate_series(1, 100) g")
    stanza.backup()
    primary.safe_sql("INSERT INTO t SELECT g, 'archived' FROM generate_series(101, 200) g")
    archive_all(primary)

    conninfo = f"host=localhost port={primary.port} application_name=standby"
    target = stanza.restore(_target("standby"), "--type=standby")
    assert (target / "standby.signal").exists()
    with _adopt(pg_install, target, signal="standby", config={"primary_conninfo": conninfo}) as standby:
        standby.start()
        primary.safe_sql("INSERT INTO t SELECT g, 'streamed' FROM generate_series(201, 300) g")
        primary.wait_for_catchup(standby)
        assert standby.sql_value("SELECT pg_is_in_recovery()") == "t"
        assert primary.sql_value("SELECT state FROM pg_stat_replication WHERE application_name = 'standby'") == (
            "streaming"
        )
        assert standby.safe_sql("SELECT v, count(*) FROM t GROUP BY v ORDER BY v") == [
            ["archived", "100"],
            ["backup", "100"],
            ["streamed", "100"],
        ]
        assert standby.is_encrypted("t") is True
        standby.expect_error(r"cannot execute INSERT in a read-only transaction", "INSERT INTO t VALUES (0, 'x')")


TABLES_SQL = "SELECT relname FROM pg_class WHERE relname LIKE 'churn\\_%' AND relkind = 'r' ORDER BY relname"


def test_backup_during_ddl_churn(pg_install, tde_node_factory, file_keyring, tmp_path):
    primary, stanza = _primary(tde_node_factory, file_keyring, tmp_path / "repo")
    done = threading.Event()
    errors = []
    events = []

    def churn():
        try:
            with primary.connect() as conn:
                i = 0
                while not done.is_set():
                    conn.safe_sql(f"CREATE TABLE churn_{i:05} (id int) USING tde_heap")
                    conn.safe_sql(f"INSERT INTO churn_{i:05} VALUES ({i})")
                    events.append(("created", f"churn_{i:05}"))
                    if i >= 5:
                        conn.safe_sql(f"DROP TABLE churn_{i - 5:05}")
                        events.append(("dropped", f"churn_{i - 5:05}"))
                    i += 1
        except Exception as e:
            errors.append(e)

    worker = threading.Thread(target=churn)
    worker.start()
    try:
        while len(events) < 10 and worker.is_alive():
            time.sleep(0.05)
        first = len(events)
        stanza.backup()
        during = events[first:]
    finally:
        done.set()
        worker.join()
    assert errors == []
    created = {t for e, t in during if e == "created"}
    dropped = {t for e, t in during if e == "dropped"}
    assert created and dropped, "no DDL while the backup ran"
    dropped_later = {t for e, t in events if e == "dropped"}
    tables = [r[0] for r in primary.safe_sql(TABLES_SQL)]
    archive_all(primary)

    with _restored(stanza, pg_install) as node:
        node.start()
        node.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        restored = [r[0] for r in node.safe_sql(TABLES_SQL)]
        assert restored == tables
        assert created - dropped_later <= set(restored)
        assert not dropped & set(restored)
        for t in restored:
            assert node.safe_sql(f"SELECT id FROM {t}") == [[str(int(t[6:]))]]
            assert node.is_encrypted(t) is True, t


@pytest.mark.parametrize(
    ("decrypt", "options", "error"),
    [
        # which header check trips depends on the ciphertext bytes
        pytest.param(
            False,
            {},
            r"ERROR: \[0(29|46)\]: (first page header in WAL file is expected to be in long format"
            r"|unexpected WAL magic)",
            id="raw-header-check",
        ),
        pytest.param(
            True,
            {"archive_async": "y"},
            r"ASSERT: \[025\]: absolute path '/dev/shm/pg_tde_archive\w+/archive_status' is not in base path",
            id="decrypt-async",
        ),
    ],
)
def test_archive_push_unsupported_options(tde_node_factory, file_keyring, tmp_path, decrypt, options, error):
    primary, stanza = _primary(tde_node_factory, file_keyring, tmp_path / "repo", decrypt=decrypt, **options)
    offset = primary.log_offset()
    primary.safe_sql("CREATE TABLE t (id int) USING tde_heap")
    # the first segment starts with a plaintext header from before the restart
    for _ in range(2):
        primary.safe_sql("INSERT INTO t VALUES (1)")
        primary.safe_sql("SELECT pg_switch_wal()")
    primary.wait_for_log(error, offset)
    primary.poll_until("SELECT failed_count > 0 FROM pg_stat_archiver")


@pytest.mark.bug("PG-2358")
def test_rewind_restores_target_wal_from_pgbackrest(pg_install, tde_node_factory, file_keyring, tmp_path):
    primary, stanza = _primary(tde_node_factory, file_keyring, tmp_path / "repo", config={"wal_keep_size": "0"})
    primary.db.add_config({"restore_command": stanza.restore_command()})
    primary.restart()
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO t SELECT g, 'shared' FROM generate_series(1, 1000) g")
    standby = TdeNode.from_backup(primary.tde_basebackup(), primary, name="standby")
    try:
        primary.wait_for_catchup(standby)
        primary.safe_sql("CHECKPOINT")
        standby.promote()
        standby.poll_until("SELECT pg_is_in_recovery()", "f")
        standby.safe_sql("INSERT INTO t VALUES (2001, 'new-primary')")
        stanza.retarget(standby)

        # the old primary diverges and recycles the segments rewind has to read back
        primary.safe_sql("INSERT INTO t VALUES (3001, 'old-primary')")
        for _ in range(3):
            archive_all(primary)
        primary.stop()
        standby.stop()
        cp = primary.tool(
            "pg_tde_rewind",
            f"--target-pgdata={primary.datadir}",
            f"--source-pgdata={standby.datadir}",
            "--restore-target-wal",
            "--debug",
        )
        st.command_ok(cp, "pg_tde_rewind --restore-target-wal")
        assert re.search(r'using file "[^"]+" restored from archive', cp.stderr), cp.stderr
        assert "invalid magic number" not in cp.stderr
        standby.start()

        primary.rejoin_as_standby(standby)
        standby.safe_sql("INSERT INTO t VALUES (2002, 'after-rewind')")
        standby.wait_for_catchup(primary)
        assert primary.safe_sql("SELECT v, count(*) FROM t GROUP BY v ORDER BY v") == [
            ["after-rewind", "1"],
            ["new-primary", "1"],
            ["shared", "1000"],
        ]
        assert primary.is_encrypted("t") is True
    finally:
        standby.close()


@pytest.mark.parametrize(
    ("decrypt", "replica"),
    [(True, "rebuild"), (False, "rebuild"), (True, "rewire")],
    ids=["decrypt-rebuild", "raw-rebuild", "decrypt-rewire"],
)
def test_replica_follows_restored_primary(pg_install, tde_node_factory, file_keyring, tmp_path, decrypt, replica):
    primary, stanza = _primary(
        tde_node_factory, file_keyring, tmp_path / "repo", decrypt=decrypt, **({} if decrypt else RAW)
    )
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO t SELECT g, 'before' FROM generate_series(1, 200) g")
    rows = [["after-restore", "1"], ["before", "200"]]
    with contextlib.ExitStack() as stack:
        if replica == "rewire":
            old = stack.enter_context(TdeNode.from_backup(primary.tde_basebackup(), primary, name="old"))
            primary.safe_sql("INSERT INTO t VALUES (201, 'streamed')")
            primary.wait_for_catchup(old)
            rows.append(["streamed", "1"])
        stanza.backup()
        archive_all(primary)
        if replica == "rewire":
            old.stop()
        primary.stop()

        restored = stack.enter_context(_restored(stanza, pg_install))
        restored.start()
        restored.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        if replica == "rewire":
            # the pre-restore replica follows the restored primary onto its new timeline
            old.db.add_config({"primary_conninfo": f"host=localhost port={restored.port} application_name=old"})
            old.start()
            node = old
        else:
            node = stack.enter_context(TdeNode.from_backup(restored.tde_basebackup(), restored, name="rebuilt"))
        restored.safe_sql("INSERT INTO t VALUES (301, 'after-restore')")
        restored.wait_for_catchup(node)
        state = restored.sql_value("SELECT state FROM pg_stat_replication WHERE application_name = $1", (node.name,))
        assert state == "streaming"
        assert node.safe_sql("SELECT v, count(*) FROM t GROUP BY v ORDER BY v") == rows
        assert node.is_encrypted("t") is True
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        if replica == "rebuild":
            # -E gave the replica WAL keys of its own
            keys = (restored.datadir / "pg_tde" / "wal_keys").read_bytes()
            assert (node.datadir / "pg_tde" / "wal_keys").read_bytes() != keys


def _raw_restore_after_restart(*args):
    # a broken setup must not pass as the expected failure of the xfail test
    try:
        return _raw_restore_after_restart_setup(*args)
    except AssertionError as e:
        raise RuntimeError("setup failed") from e


def _raw_restore_after_restart_setup(pg_install, tde_node_factory, keyring, tmp_path, keys):
    # rows 1 and 2 before a primary restart, row 3 after it, under a WAL key the backup lacks
    primary, stanza = _primary(tde_node_factory, keyring, tmp_path / "repo", decrypt=False, **RAW)
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY) USING tde_heap")
    primary.safe_sql("INSERT INTO t VALUES (1)")
    stanza.backup()
    with TdeNode.from_backup(primary.tde_basebackup(), primary, name="standby") as standby:
        primary.safe_sql("INSERT INTO t VALUES (2)")
        primary.wait_for_catchup(standby)
        standby_keys = tmp_path / "standby_keys"
        shutil.copytree(standby.datadir / "pg_tde", standby_keys)
    primary.restart()
    primary.safe_sql("INSERT INTO t VALUES (3)")
    archive_all(primary)
    live_keys = tmp_path / "live_keys"
    shutil.copytree(primary.datadir / "pg_tde", live_keys)
    primary.stop()

    target = stanza.restore(_target())
    if keys != "backup":
        shutil.rmtree(target / "pg_tde")
        shutil.copytree(live_keys if keys == "live" else standby_keys, target / "pg_tde")
    return _adopt(pg_install, target)


@pytest.mark.parametrize("keys", ["live", "standby"])
def test_raw_archive_replay_needs_writer_wal_keys(pg_install, tde_node_factory, file_keyring, tmp_path, keys):
    with _raw_restore_after_restart(pg_install, tde_node_factory, file_keyring, tmp_path, keys) as node:
        offset = node.log_offset()
        if keys == "standby":
            with pytest.raises(RuntimeError, match="server did not become ready"):
                node.start()
            log = node.log_since(offset)
            assert re.search(r"LOG:  invalid magic number [0-9A-F]{4} in WAL segment \w{24}, LSN \S+, offset 0", log)
            assert "FATAL:  could not locate required checkpoint record" in log
            return
        node.start()
        node.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        assert node.safe_sql(IDS_SQL) == [["1"], ["2"], ["3"]]


@pytest.mark.bug("PG-2872")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="PG-2872: replay stops silently at WAL encrypted with a key missing from the backup",
)
def test_raw_archive_replay_with_backup_keys_loses_no_rows(pg_install, tde_node_factory, file_keyring, tmp_path):
    with _raw_restore_after_restart(pg_install, tde_node_factory, file_keyring, tmp_path, "backup") as node:
        offset = node.log_offset()
        try:
            node.start()
        except RuntimeError:
            # refusing to start is fine, as long as it says the key is missing
            assert re.search(r"(FATAL|PANIC): .*key", node.log_since(offset)), node.log_since(offset)
            return
        node.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        assert node.safe_sql(IDS_SQL) == [["1"], ["2"], ["3"]], "promoted past the unreadable WAL"


def _pg_wal_layout(node, layout, tmp_path):
    wal = node.datadir / "pg_wal"
    if layout == "plain":
        return
    real = node.datadir / "wal_volume" if layout == "nested" else tmp_path / "wal_volume"
    shutil.move(wal, real)
    if layout == "sibling":
        wal.symlink_to(real)
    else:
        wal.symlink_to(os.path.relpath(real, node.datadir) if layout == "sibling-relative" else real.name)


def _archive_midstream_wal_encrypt(tde_node_factory, keyring, tmp_path, layout):
    node = tde_node_factory("primary", config=CONFIG, start=False)
    _pg_wal_layout(node, layout, tmp_path)
    node.start()
    stanza = Stanza(node, tmp_path / "repo", **OPTIONS)
    node.db.add_config(stanza.archive_config())
    node.restart()
    stanza.create()
    offset = node.log_offset()

    # plaintext WAL through the same archive command first, keys come later
    node.safe_sql("CREATE TABLE p (id int PRIMARY KEY) USING heap")
    node.safe_sql("INSERT INTO p SELECT generate_series(1, 1000)")
    archive_all(node)
    node.setup_default_key(keyring)
    api.set_wal_encrypt(node, True)
    node.safe_sql("SELECT pg_reload_conf()")
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "off", "wal_encrypt needs a restart"
    node.restart()
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    for i in range(3):
        node.safe_sql(f"INSERT INTO t SELECT g, repeat('x', 80) FROM generate_series({i * 500 + 1}, {i * 500 + 500}) g")
        archive_all(node)

    assert "mismatch of segment size" not in node.log_since(offset)
    assert node.sql_value("SELECT failed_count FROM pg_stat_archiver") == "0"
    return node, stanza


@pytest.mark.bug("PG-2609")
@pytest.mark.parametrize("layout", ["plain", "sibling", "sibling-relative"])
def test_archive_decrypt_with_pg_wal_symlink(pg_install, tde_node_factory, keyring_obj, tmp_path, layout):
    node, stanza = _archive_midstream_wal_encrypt(tde_node_factory, keyring_obj, tmp_path, layout)
    if layout == "sibling-relative":
        assert not os.readlink(node.datadir / "pg_wal").startswith("/")
    stanza.backup()
    with _restored(stanza, pg_install) as restored:
        restored.start()
        restored.poll_until("SELECT pg_is_in_recovery()", "f", timeout=60)
        assert restored.safe_sql("SELECT count(*), sum(id) FROM t") == [["1500", "1125750"]]
        assert restored.safe_sql("SELECT count(*) FROM p") == [["1000"]]
        assert restored.is_encrypted("t") is True
        assert restored.sql_value("SHOW pg_tde.wal_encrypt") == "on"


def test_archive_decrypt_with_pg_wal_link_inside_pgdata(tde_node_factory, file_keyring, tmp_path):
    # the key dir derived from pg_wal/.. stays right, the wrapper archives
    node, stanza = _archive_midstream_wal_encrypt(tde_node_factory, file_keyring, tmp_path, "nested")
    # pgBackRest refuses links into PGDATA on its own
    assert stanza.run("--type=full", "backup").returncode != 0
