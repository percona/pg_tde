import re

import pytest
import stormweaver.testing as st

from pgtde.standby import standby_from_backup_dir

# tmpfs mount point for temporary files is Linux specific
pytestmark = pytest.mark.linux_only

HELP = {
    "pg_tde_archive_decrypt": r"wraps an archive command to give the command unencrypted WAL",
    "pg_tde_restore_encrypt": r"wraps a restore command to encrypt its returned WAL",
}


@pytest.mark.parametrize("tool", ["pg_tde_archive_decrypt", "pg_tde_restore_encrypt"])
def test_cli(tools, tool):
    param = "ARCHIVE-COMMAND" if tool.endswith("decrypt") else "RESTORE-COMMAND"

    cp = tools.run(tool, "--help")
    st.command_ok(cp)
    assert re.search(HELP[tool], cp.stdout), cp.stdout

    cp = tools.run(tool, "--version")
    st.command_ok(cp)
    assert re.search(rf"{tool} \(PostgreSQL\) ", cp.stdout), cp.stdout

    st.command_fails(tools.run(tool, "a", "b"), stderr_re=r"error: wrong number of arguments, 3 expected")
    st.command_fails(
        tools.run(tool, "file", "pg_wal/file", "false %q"),
        stderr_re=rf'error: invalid value for parameter "{param}": "false %q"\n'
        r'.*?detail: String contains unexpected placeholder "%q"',
    )
    st.command_fails(
        tools.run(tool, "file", "pg_wal/file", "unknown_command_42"),
        stderr_re=rf'error: {param} "unknown_command_42" failed with exit code 127',
    )
    st.command_fails(
        tools.run(tool, "file", "pg_wal/file", "false"), stderr_re=rf'error: {param} "false" failed with exit code 1'
    )
    st.command_fails(
        tools.run(tool, "file", "pg_wal/file", "kill $$; sleep"),
        stderr_re=rf'error: {param} "kill \$\$; sleep" was terminated by signal 15: Terminated',
    )


def _replica(backup, pg_install, archive, name):
    restore = pg_install.bindir / "pg_tde_restore_encrypt"
    return standby_from_backup_dir(
        backup,
        pg_install.install_dir,
        name=name,
        config={"restore_command": f'{restore} %f %p "cp {archive}/%%f %%p"', "archive_mode": "off"},
    )


def _start_restoring(replica):
    # server logs are per session, skip what earlier tests appended
    offset = replica.log_offset()
    replica.start()
    replica.wait_for_log("waiting for WAL to become available", offset)


def test_wal_archiving(pg_install, tde_node_factory, keyring_obj, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    decrypt = pg_install.bindir / "pg_tde_archive_decrypt"
    config = {
        "wal_level": "replica",
        "autovacuum": "off",
        "checkpoint_timeout": "1h",
        "archive_mode": "on",
        "archive_command": f'{decrypt} %f %p "cp %%p {archive}/%%f"',
    }
    primary = tde_node_factory("primary", config=config)
    primary.setup_server_key(keyring_obj, provider="keyring", key="server-key")

    # one backup taken with plain WAL and one with encrypted WAL, then
    # some plaintext WAL and some encrypted WAL
    plain_wal = primary.basebackup(extra_args=["-X", "none"])

    primary.db.add_config({"pg_tde.wal_encrypt": "on"})
    primary.restart()

    enc_wal = primary.basebackup(extra_args=["-X", "none"])

    primary.db.add_config({"pg_tde.wal_encrypt": "off"})
    primary.restart()

    primary.db.add_config({"pg_tde.wal_encrypt": "on"})
    primary.safe_sql("CREATE TABLE t1 AS SELECT 'foobar_plain' AS x")
    primary.restart()
    primary.safe_sql("CREATE TABLE t2 AS SELECT 'foobar_enc' AS x")

    s = st.wal_strings(primary.datadir / "pg_wal")
    assert "foobar_plain" in s, "should find foobar_plain in WAL"
    assert "foobar_enc" not in s, "should not find foobar_enc in WAL since it is encrypted"

    primary.stop()

    s = st.wal_strings(archive)
    assert "foobar_plain" in s, "should find foobar_plain in archive"
    assert "foobar_enc" in s, "should find foobar_enc in archive"

    # restore_command with encrypted WAL
    with _replica(enc_wal, pg_install, archive, "replica_enc") as replica:
        _start_restoring(replica)
        s = st.wal_strings(replica.datadir / "pg_wal")
        assert "foobar_plain" not in s, "should not find foobar_plain in WAL since it is encrypted"
        assert "foobar_enc" not in s, "should not find foobar_enc in WAL since it is encrypted"
        replica.promote()
        assert replica.safe_sql("SELECT * FROM t1 UNION ALL SELECT * FROM t2") == [["foobar_plain"], ["foobar_enc"]]

    # restore_command with plain WAL
    with _replica(plain_wal, pg_install, archive, "replica_plain") as replica:
        _start_restoring(replica)
        s = st.wal_strings(replica.datadir / "pg_wal")
        assert "foobar_plain" in s, "should find foobar_plain in WAL since it is not encrypted"
        assert "foobar_enc" in s, "should find foobar_enc in WAL since it is not encrypted"
        replica.promote()
        assert replica.safe_sql("SELECT * FROM t1 UNION ALL SELECT * FROM t2") == [["foobar_plain"], ["foobar_enc"]]
