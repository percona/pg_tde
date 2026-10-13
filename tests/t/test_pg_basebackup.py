import stormweaver.testing as st

from pgtde.node import TdeNode


def test_pg_basebackup(pg_install_dir, sw_log_dir, tools, tmp_path):
    tools.help_ok("pg_tde_basebackup")
    tools.version_ok("pg_tde_basebackup")
    tools.options_ok("pg_tde_basebackup")

    backup = tmp_path / "backup"
    with TdeNode.fresh(pg_install_dir, name="main", initdb_args=["--data-checksums"]) as node:

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
        st.command_fails(
            bb("-E"), stderr_re=r"could not find server principal key", msg="encryption with no pg_tde dir"
        )
        st.command_fails(
            bb("--encrypt-wal"),
            stderr_re=r"could not find server principal key",
            msg="encryption with no pg_tde dir long flag",
        )
