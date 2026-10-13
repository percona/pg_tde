import tempfile
from pathlib import Path

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.node import TdeNode


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


def test_pg_tde_upgrade(pg_install_dir, tde_node_factory, node_config, tools, tmp_path, socketdir):
    tools.help_ok("pg_tde_upgrade")
    tools.version_ok("pg_tde_upgrade")
    tools.options_ok("pg_tde_upgrade")

    # keep delete_old_cluster.sh out of the source dir
    workdir = tmp_path / "work"
    workdir.mkdir()

    oldnotde = tde_node_factory("oldnotde", preload="")
    # pg_upgrade target, not started
    with TdeNode.unstarted(pg_install_dir, name="newnotde", config=node_config, preload="") as newnotde:
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

    keydir = tmp_path / "keys"
    keydir.mkdir()
    old = tde_node_factory("old")
    with TdeNode.unstarted(pg_install_dir, name="new", config=node_config | {"pg_tde.wal_encrypt": "on"}) as new:
        old.setup_server_key(Path(keydir) / "global.keys", provider="file-vault", key="server-key")
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
