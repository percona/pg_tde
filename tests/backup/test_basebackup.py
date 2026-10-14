import json
import re
import shutil
import threading
import time

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.node import TdeNode
from pgtde.wal import wal_contains


@pytest.mark.node_config(initdb_args=["--data-checksums"])
def test_basebackup(tde_node, tools, tmp_path):
    tools.help_ok("pg_tde_basebackup")
    tools.version_ok("pg_tde_basebackup")
    tools.options_ok("pg_tde_basebackup")

    backup = tmp_path / "backup"
    node = tde_node

    def bb(*args):
        return node.tool("pg_tde_basebackup", "-D", backup, *args)

    st.command_fails(bb("-E", "-Ft"), stderr_re=r"can not encrypt WAL in tar mode", msg="encryption in tar mode")
    st.command_fails(
        bb("-E", "-X", "fetch"),
        stderr_re=r"WAL encryption can only be used with WAL streaming",
        msg="encryption with WAL fetch",
    )
    st.command_fails(
        bb("-E", "-X", "none"),
        stderr_re=r"WAL encryption can only be used with WAL streaming",
        msg="encryption with WAL none",
    )
    st.command_fails(bb("-E"), stderr_re=r"could not find server principal key", msg="encryption with no pg_tde dir")
    st.command_fails(
        bb("--encrypt-wal"),
        stderr_re=r"could not find server principal key",
        msg="encryption with no pg_tde dir long flag",
    )


def test_basebackup_default_key(tde_node, keyring_obj, tmp_path):
    node = tde_node
    node.setup_default_key(keyring_obj, provider="global-provider", key="key1")
    # server key used to materialize only on next start, -E backup failed
    assert api.server_key_info(node) == ["-1", "global-provider", "key1"]
    node.tde_basebackup(tmp_path / "bk", "-X", "stream")


WAL_KEYS_WARNING = "the source has WAL keys, but no WAL encryption configured for the target backups"


def _db_key(node):
    api.create_key(node, "db-key", "global-provider", scope="global")
    api.set_key(node, "db-key", "global-provider", scope="global")


def _lsn(s):
    hi, lo = s.split("/")
    return int(hi, 16) << 32 | int(lo, 16)


def _tde_basebackup_during_writes(node, *args):
    # rows written while the backup runs land in the streamed WAL
    done = threading.Event()
    first = threading.Event()
    errors = []

    def write():
        try:
            with node.connect() as conn:
                while not done.is_set():
                    conn.safe_sql("INSERT INTO t VALUES ('streamed-wal-marker')")
                    first.set()
                    time.sleep(0.01)
        except Exception as e:
            errors.append(e)
        finally:
            first.set()

    worker = threading.Thread(target=write)
    worker.start()
    try:
        first.wait(30)
        assert errors == []
        cp = node.tool("pg_tde_basebackup", *args)
    finally:
        done.set()
        worker.join()
    assert errors == []
    return cp


def test_basebackup_encrypt_wal_flag(tde_node_global, tmp_path):
    node = tde_node_global
    _db_key(node)
    node.safe_sql("CREATE TABLE t (v text) USING tde_heap")
    for encrypt in (False, True):
        dest = tmp_path / f"backup-{encrypt}"
        args = ["-D", dest, "-X", "stream", "--checkpoint=fast", "--no-sync"]
        if encrypt:
            # -E needs the keys up front
            shutil.copytree(node.datadir / "pg_tde", dest / "pg_tde")
            args.append("-E")
        cp = _tde_basebackup_during_writes(node, *args)
        st.command_ok(cp)
        assert (WAL_KEYS_WARNING in cp.stderr) is not encrypt, cp.stderr
        assert wal_contains(dest / "pg_wal", "streamed-wal-marker") is not encrypt

        label = (dest / "backup_label").read_text()
        start = re.search(r"START WAL LOCATION: (\S+) ", label).group(1)
        ckpt = _lsn(re.search(r"CHECKPOINT LOCATION: (\S+)", label).group(1))
        end = json.loads((dest / "backup_manifest").read_text())["WAL-Ranges"][-1]["End-LSN"]
        dump = node.tool("pg_waldump", "-p", dest / "pg_wal", "-s", start, "-e", end)
        if encrypt:
            assert dump.returncode != 0
            # the page header is encrypted too, the segment size read from it is garbage
            seg_size = r'invalid WAL segment size in WAL file "\w{24}"|but the WAL file "\w{24}" header specifies'
            assert re.search(seg_size, dump.stderr), dump.stderr
        else:
            st.command_ok(dump, "streamed WAL is plaintext without -E")
            recs = {_lsn(m[0]): m[1] for m in re.findall(r"lsn: (\S+), prev \S+, desc: (\S+)", dump.stdout)}
            assert recs.get(ckpt) == "CHECKPOINT_ONLINE", dump.stdout


def test_rebuild_old_primary_from_promoted_standby(tde_node_global):
    primary = tde_node_global
    _db_key(primary)
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY) USING tde_heap")
    primary.safe_sql("INSERT INTO t SELECT generate_series(1, 1000)")
    with TdeNode.from_backup(primary.tde_basebackup(), primary, name="standby") as standby:
        primary.wait_for_catchup(standby)
        primary.stop()
        standby.promote()
        standby.poll_until("SELECT pg_is_in_recovery()", "f")
        standby.safe_sql("INSERT INTO t SELECT generate_series(1001, 2000)")
        # the old primary comes back as a new copy of the promoted node
        with TdeNode.from_backup(standby.tde_basebackup(), standby, name="rebuilt") as rebuilt:
            standby.safe_sql("INSERT INTO t SELECT generate_series(2001, 3000)")
            standby.wait_for_catchup(rebuilt)
            assert rebuilt.safe_sql("SELECT count(*), sum(id) FROM t") == [["3000", "4501500"]]
            assert rebuilt.is_encrypted("t") is True
            assert rebuilt.sql_value("SHOW pg_tde.wal_encrypt") == "on"
            rebuilt.restart()
            assert rebuilt.safe_sql("SELECT count(*) FROM t") == [["3000"]]


@pytest.mark.parametrize(
    ("broken", "errors"),
    [
        pytest.param("keys", [r"FATAL:  principal key not configured"], id="no-pg_tde-dir"),
        pytest.param(
            "preload",
            [
                r"invalid magic number [0-9A-F]{4} in WAL segment \w{24}, LSN \S+, offset 0",
                r"FATAL:  could not locate required checkpoint record",
            ],
            id="no-preload",
        ),
    ],
)
def test_restore_without_pg_tde_fails(pg_install, tde_node_global, broken, errors):
    node = tde_node_global
    _db_key(node)
    node.safe_sql("CREATE TABLE t (id int) USING tde_heap")
    node.safe_sql("INSERT INTO t VALUES (1)")
    backup = node.tde_basebackup(None, "-X", "stream")
    config = {}
    if broken == "keys":
        shutil.rmtree(backup / "pg_tde")
    else:
        config["shared_preload_libraries"] = ""
    with TdeNode.adopt(pg_install.install_dir, backup, name="restored", config=config) as restored:
        offset = restored.log_offset()
        with pytest.raises(RuntimeError, match="server did not become ready"):
            restored.start()
        with open(restored.server_log, errors="replace") as f:
            f.seek(offset)
            log = f.read()
        for error in errors:
            assert re.search(error, log), log
