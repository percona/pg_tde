import tempfile
from pathlib import Path

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.upgrade import update_extension


def _upgrade(node, old, new, socketdir, cwd):
    bindir = Path(node.db.install_dir) / "bin"
    return node.tool(
        "pg_tde_upgrade",
        "--no-sync",
        "--old-datadir",
        old.datadir,
        "--new-datadir",
        new.datadir,
        "--old-bindir",
        bindir,
        "--new-bindir",
        bindir,
        "--socketdir",
        socketdir,
        "--old-port",
        str(old.port),
        "--new-port",
        str(new.port),
        cwd=cwd,
    )


@pytest.fixture
def socketdir():
    # tmp_path may be too long for a unix socket path
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        yield d


def test_pg_tde_upgrade(tde_node_factory, file_keyring, tools, tmp_path, socketdir):
    tools.help_ok("pg_tde_upgrade")
    tools.version_ok("pg_tde_upgrade")
    tools.options_ok("pg_tde_upgrade")

    # keep delete_old_cluster.sh out of the source dir
    workdir = tmp_path / "work"
    workdir.mkdir()

    oldnotde = tde_node_factory("oldnotde", preload="")
    newnotde = tde_node_factory("newnotde", start=False, preload="")
    oldnotde.safe_sql("CREATE TABLE test_plain (k int, PRIMARY KEY (k))")
    oldnotde.safe_sql("INSERT INTO test_plain (k) VALUES (1), (2)")
    oldnotde.stop()

    st.command_ok(
        _upgrade(newnotde, oldnotde, newnotde, socketdir, workdir),
        "executes pg_upgrade successfully without pg_tde",
    )

    newnotde.start()
    assert newnotde.safe_sql("SELECT * FROM test_plain") == [["1"], ["2"]]
    newnotde.stop()

    old = tde_node_factory("old")
    new = tde_node_factory("new", start=False, config={"pg_tde.wal_encrypt": "on"})
    old.setup_server_key(file_keyring, provider="file-vault", key="server-key")
    api.set_key(old, "server-key", "file-vault", scope="global")
    api.set_wal_encrypt(old, True)
    old.safe_sql("CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap")
    old.safe_sql("INSERT INTO test_enc (k) VALUES (1), (2)")
    old.restart()
    old.stop()

    st.command_ok(_upgrade(new, old, new, socketdir, workdir), "executes pg_upgrade successfully with pg_tde")

    new.start()
    assert new.safe_sql("SELECT * FROM test_enc") == [["1"], ["2"]]
    new.stop()


def _encrypted_old(upgrade, tde_node_factory, keyring_obj, name="old"):
    old = upgrade.old_node(tde_node_factory, name)
    old.setup_server_key(keyring_obj)
    api.set_key(old, "server-key", "global-provider", scope="global")
    old.safe_sql(
        "CREATE TABLE t_enc (k int PRIMARY KEY) USING tde_heap; INSERT INTO t_enc SELECT generate_series(1, 100)"
    )
    return old


@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_keeps_encrypted_data(upgrade, tde_node_factory, keyring_obj, tmp_path, socketdir):
    old = _encrypted_old(upgrade, tde_node_factory, keyring_obj)
    new = upgrade.new_node(tde_node_factory, "new", old)
    workdir = tmp_path / "work"
    workdir.mkdir()
    st.command_ok(upgrade.run_pg_tde_upgrade(old, new, socketdir=socketdir, cwd=workdir), "pg_tde_upgrade")
    new.start()
    update_extension(new)
    assert api.tde_version(new) == upgrade.suite_tde
    assert new.sql_value("SELECT count(*) FROM t_enc") == "100"
    assert api.is_encrypted(new, "t_enc")


@pytest.mark.old_install(same_major=True)
def test_in_place_start_keeps_encrypted_data(upgrade, tde_node_factory, keyring_obj):
    node = _encrypted_old(upgrade, tde_node_factory, keyring_obj, name="inplace")
    assert api.tde_version(node) == upgrade.old_tde
    upgrade.start_in_place(node)
    assert api.tde_version(node) == upgrade.suite_tde
    assert node.sql_value("SELECT count(*) FROM t_enc") == "100"
    node.restart()
    assert node.sql_value("SELECT count(*) FROM t_enc") == "100"
