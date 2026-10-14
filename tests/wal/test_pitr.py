import pytest

from pgtde import api
from pgtde.standby import standby_from_backup_dir
from pgtde.wal import archive_config, wal_contains

CONFIG = {"wal_level": "replica", "autovacuum": "off", "checkpoint_timeout": "1h"}
IDS_SQL = "SELECT id FROM t ORDER BY id"


def _primary(tde_node_factory, pg_install, keyring_obj, archive):
    archive.mkdir()
    primary = tde_node_factory("primary", config=CONFIG | archive_config(pg_install.bindir, archive, restore=True))
    primary.setup_server_key(keyring_obj, wal_encrypt=True)
    api.create_key(primary, "db-key", "global-provider", scope="global")
    api.set_key(primary, "db-key", "global-provider", scope="global")
    primary.restart()
    return primary


def _archive_all(node):
    seg = node.sql_value("SELECT pg_walfile_name(pg_switch_wal())")
    node.poll_until(f"SELECT coalesce(last_archived_wal >= '{seg}', false) FROM pg_stat_archiver")


def _restore(backup, pg_install, recovery):
    # restore_command comes with the backup's postgresql.conf
    config = {"archive_mode": "off", **recovery}
    return standby_from_backup_dir(backup, pg_install.install_dir, name="pitr", config=config, signal="recovery")


def _target(kind, inclusive=True, action="promote", expected=("1", "2")):
    rows = [[i] for i in expected]
    name = f"{kind}{'' if inclusive else '-exclusive'}{'' if action == 'promote' else '-' + action}"
    return pytest.param(kind, inclusive, action, rows, id=name)


@pytest.mark.parametrize(
    ("kind", "inclusive", "action", "expected"),
    [
        _target("time"),
        _target("lsn"),
        _target("lsn", inclusive=False),
        _target("xid"),
        _target("xid", inclusive=False, expected=("1",)),
        _target("time", action="pause"),
    ],
)
def test_pitr_to_target(pg_install, tde_node_factory, keyring_obj, tmp_path, kind, inclusive, action, expected):
    primary = _primary(tde_node_factory, pg_install, keyring_obj, tmp_path / "archive")
    primary.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO t VALUES (1, 'base')")
    primary.safe_sql("CREATE TABLE d (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO d VALUES (1, 'dropped-later')")
    backup = primary.tde_basebackup()

    primary.safe_sql("INSERT INTO t VALUES (2, 'target')")
    xid = primary.sql_value("SELECT xmin FROM t WHERE id = 2")
    # after commit 2, before commit 3
    [[lsn, ts]] = primary.safe_sql("SELECT pg_current_wal_lsn(), clock_timestamp()")
    primary.safe_sql("INSERT INTO t VALUES (3, 'after')")
    primary.safe_sql("DROP TABLE d")
    _archive_all(primary)

    recovery = {
        f"recovery_target_{kind}": {"time": ts, "lsn": lsn, "xid": xid}[kind],
        "recovery_target_inclusive": "on" if inclusive else "off",
        "recovery_target_action": action,
    }
    with _restore(backup, pg_install, recovery) as node:
        node.start()
        if action == "pause":
            node.poll_until("SELECT pg_get_wal_replay_pause_state()", "paused")
            assert node.sql_value("SELECT pg_is_in_recovery()") == "t"
            assert node.safe_sql(IDS_SQL) == expected
            node.safe_sql("SELECT pg_wal_replay_resume()")
        node.poll_until("SELECT pg_is_in_recovery()", "f")
        assert node.safe_sql(IDS_SQL) == expected
        assert node.is_encrypted("t")
        assert node.safe_sql("SELECT id, v FROM d") == [["1", "dropped-later"]]
        assert node.is_encrypted("d")

        # new timeline keeps encrypting WAL
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        node.safe_sql("INSERT INTO t VALUES (4, 'pitr-promoted-marker')")
        assert not wal_contains(node, "pitr-promoted-marker")
        node.restart()
        assert node.safe_sql(IDS_SQL) == [*expected, ["4"]]


def test_pitr_before_drop_database(pg_install, tde_node_factory, keyring_obj, tmp_path):
    primary = _primary(tde_node_factory, pg_install, keyring_obj, tmp_path / "archive")
    primary.safe_sql("CREATE TABLE keep_me (id int PRIMARY KEY, v text) USING tde_heap")
    primary.safe_sql("INSERT INTO keep_me VALUES (1, 'postgres-row')")
    backup = primary.tde_basebackup()

    # appdb, its key and its table only exist in the archived WAL
    primary.safe_sql("CREATE DATABASE appdb")
    with primary.connect(db="appdb") as conn:
        api.create_extension(conn)
        api.create_key(conn, "appdb-key", "global-provider", scope="global")
        api.set_key(conn, "appdb-key", "global-provider", scope="global")
        conn.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
        conn.safe_sql("INSERT INTO t VALUES (10, 'appdb-row')")
    lsn = primary.sql_value("SELECT pg_current_wal_lsn()")
    primary.safe_sql("DROP DATABASE appdb")
    _archive_all(primary)

    recovery = {
        "recovery_target_lsn": lsn,
        "recovery_target_inclusive": "off",
        "recovery_target_action": "promote",
    }
    with _restore(backup, pg_install, recovery) as node:
        node.start()
        node.poll_until("SELECT pg_is_in_recovery()", "f")
        assert node.safe_sql("SELECT id, v FROM keep_me") == [["1", "postgres-row"]]
        # -2 marks a database whose DROP was interrupted
        assert node.sql_value("SELECT datconnlimit FROM pg_database WHERE datname = 'appdb'") == "-1"
        with node.connect(db="appdb") as conn:
            assert conn.safe_sql("SELECT id, v FROM t") == [["10", "appdb-row"]]
            assert api.is_encrypted(conn, "t")
            assert api.key_info(conn)[1:] == ["global-provider", "appdb-key"]
