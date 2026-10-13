import re

import stormweaver.testing as st

from pgtde.node import TdeNode


def test_pg_waldump_tde_rmgr(pg_install_dir, sw_log_dir, tools, tmp_path):
    config = {"autovacuum": "off", "checkpoint_timeout": "1h"}
    with TdeNode.fresh(pg_install_dir, name="main", config=config) as node:
        start_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")

        # XLOG_TDE_INSTALL_EXTENSION, XLOG_TDE_WRITE_KEY_PROVIDER,
        # XLOG_TDE_ADD_PRINCIPAL_KEY
        node.setup_server_key(tmp_path / "global.keys", provider="file-keyring-wal", key="server-key")

        end_lsn = node.sql_value("SELECT pg_current_wal_insert_lsn()")
        node.stop()

        def test_waldump(*opts):
            cp = node.tool(
                "pg_tde_waldump",
                "-k",
                node.datadir / "pg_tde",
                "-p",
                node.datadir,
                "--start",
                start_lsn,
                "--end",
                end_lsn,
                *opts,
            )
            st.command_ok(cp, f"pg_tde_waldump {opts}: runs ok")
            assert cp.stderr == "", f"pg_tde_waldump {opts}: no stderr"
            lines = cp.stdout.split("\n")
            while lines and lines[-1] == "":
                lines.pop()
            assert len(lines) > 0, f"pg_tde_waldump {opts}: some lines are output"
            return lines

        def count(pat, lines):
            return sum(1 for ln in lines if re.search(pat, ln))

        lines = test_waldump()
        assert count(r"^rmgr: pg_tde\b", lines) > 0, "pg_tde rmgr lines are present"
        assert count(r"^rmgr: custom140\b", lines) == 0, "no unresolved custom140 rmgr lines"
        assert count(r"^rmgr: pg_tde\b.*\bdesc: UNKNOWN\b", lines) == 0, (
            "no unresolved UNKNOWN description for pg_tde records"
        )
        for desc in ("INSTALL_EXTENSION", "WRITE_KEY_PROVIDER", "ADD_PRINCIPAL_KEY"):
            assert count(rf"^rmgr: pg_tde\b.*\bdesc: {desc}\b", lines) > 0, f"{desc} record is described"

        cp = tools.run("pg_tde_waldump", "--rmgr", "list")
        st.command_ok(cp, "pg_tde_waldump --rmgr=list runs ok")
        assert re.search(r"^pg_tde$", cp.stdout, re.M), "pg_tde is listed as a known rmgr"

        lines = test_waldump("--rmgr", "pg_tde")
        assert len(lines) > 0, "at least one pg_tde record found when filtering by name"
        assert len(lines) == count(r"^rmgr: pg_tde\b", lines), "only pg_tde lines with --rmgr=pg_tde"

        lines_legacy = test_waldump("--rmgr", "custom140")
        assert len(lines_legacy) == count(r"^rmgr: pg_tde\b", lines_legacy), (
            "only pg_tde lines with legacy --rmgr=custom140"
        )
        assert lines == lines_legacy, "--rmgr=pg_tde and --rmgr=custom140 select the same records"
