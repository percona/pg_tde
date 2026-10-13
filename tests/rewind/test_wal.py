import re


# Target data directory contains WAL files already recycled by the new primary.
def test_keep_recycled_wals(rewind_driver):
    with rewind_driver() as rw:
        p = rw.setup_primary()
        p.db.enable_archiving()
        p.restart()

        s = rw.create_standby()
        s.db.enable_restoring(p.db)
        s.safe_sql("SELECT pg_reload_conf()")

        p.safe_sql("CHECKPOINT")  # last common checkpoint

        p.db.add_config({"archive_command": "false"})
        p.safe_sql("SELECT pg_reload_conf()")

        # this WAL segment never makes it to the archive
        p.safe_sql("CREATE TABLE t(a int)")
        p.safe_sql("INSERT INTO t VALUES(0)")
        p.safe_sql("SELECT pg_switch_wal()")

        rw.promote_standby()

        # new primary loses diverging WAL segment
        s.safe_sql("INSERT INTO t values(0)")
        s.safe_sql("SELECT pg_switch_wal()")

        s.stop()
        p.stop()

        cp = p.tool(rw.rewind_bin, "--debug", "--source-pgdata", s.datadir, "--target-pgdata", p.datadir, "--no-sync")
        assert re.search(r"Not removing file .* because it is required for recovery", cp.stderr), cp.stderr
