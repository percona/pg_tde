import stormweaver.testing as st


def test_pg_basebackup(tde_node_factory, tools, tmp_path):
    tools.help_ok("pg_tde_basebackup")
    tools.version_ok("pg_tde_basebackup")
    tools.options_ok("pg_tde_basebackup")

    backup = tmp_path / "backup"
    node = tde_node_factory("main", initdb_args=["--data-checksums"])

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
