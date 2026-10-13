import subprocess
from pathlib import Path

from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import TdeRewindDriver


def test_pg_rewind_growing_files(pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher="aes_128", keyring=kr, debug=True) as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE tbl1 (d text)")
        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary')")
        p.safe_sql("CHECKPOINT")

        s = rw.create_standby()

        p.safe_sql("INSERT INTO tbl1 values ('in primary, before promotion')")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary, after promotion')")
        s.safe_sql("INSERT INTO tbl1 VALUES ('in standby, after promotion')")

        s.stop()
        p.stop()

        grow = s.datadir / "tst_both_dir" / "file1"
        grow.parent.mkdir()
        grow.write_text("a")

        # stderr goes into a file being copied, so it grows during the copy
        with open(grow, "a") as err:
            rc = subprocess.run(
                [
                    str(Path(pg_install_dir) / "bin" / rw.rewind_bin),
                    "--debug",
                    "--source-pgdata",
                    str(s.datadir),
                    "--target-pgdata",
                    str(p.datadir),
                    "--no-sync",
                ],
                stdout=subprocess.DEVNULL,
                stderr=err,
                stdin=subprocess.DEVNULL,
            ).returncode
        assert rc != 0, "error out on copying growing file"

        target = p.datadir / "tst_both_dir" / "file1"
        assert grow.stat().st_size != target.stat().st_size
        last = grow.read_text().splitlines()[-1]
        assert "error: size of source file" in last
