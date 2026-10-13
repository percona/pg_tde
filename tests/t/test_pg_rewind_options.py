import stormweaver.testing as st


def test_pg_rewind_options(tools, tmp_path):
    tools.help_ok("pg_tde_rewind")
    tools.version_ok("pg_tde_rewind")
    tools.options_ok("pg_tde_rewind")

    primary = tmp_path / "primary"
    standby = tmp_path / "standby"
    primary.mkdir()
    standby.mkdir()
    local = ("--target-pgdata", primary, "--source-pgdata", standby)

    st.command_fails(tools.run("pg_tde_rewind", "--debug", *local, "extra_arg1"), msg="too many arguments")
    st.command_fails(tools.run("pg_tde_rewind", "--target-pgdata", primary), msg="no source specified")
    st.command_fails(
        tools.run("pg_tde_rewind", "--debug", *local, "--source-server", "incorrect_source"),
        msg="both remote and local sources specified",
    )
    st.command_fails(
        tools.run("pg_tde_rewind", "--debug", *local, "--write-recovery-conf"),
        msg="no local source with --write-recovery-conf",
    )
