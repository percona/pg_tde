import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pgtde.rewind import TdeRewindDriver


def _put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(text)


# How pg_tde_rewind reacts to extra files and directories in the data dirs.
@pytest.mark.parametrize("mode", ["local", "remote"])
def test_extrafiles(mode, rewind_driver):
    with rewind_driver() as rw:
        p = rw.setup_primary()
        pd = p.datadir

        _put(pd / "tst_both_dir/both_file1", "in both1")
        _put(pd / "tst_both_dir/both_file2", "in both2")
        _put(pd / "tst_both_dir/both_subdir/both_file3", "in both3")

        s = rw.create_standby()
        sd = s.datadir

        _put(sd / "tst_standby_dir/standby_file1", "in standby1")
        _put(sd / "tst_standby_dir/standby_file2", "in standby2")
        _put(sd / "tst_standby_dir/standby_file3 with 'quotes'", "in standby3")
        _put(sd / "tst_standby_dir/standby_subdir/standby_file4", "in standby4")
        if sys.platform != "darwin":
            _put(sd / "tst_standby_dir/.DS_Store", "macOS system file")

        _put(pd / "tst_primary_dir/primary_file1", "in primary1")
        _put(pd / "tst_primary_dir/primary_file2", "in primary2")
        _put(pd / "tst_primary_dir/primary_subdir/primary_file3", "in primary3")

        rw.promote_standby()
        rw.run_rewind(mode)

        paths = sorted(str(x) for x in pd.rglob("*") if "tst_" in str(x))
        assert paths == [
            f"{pd}/tst_both_dir",
            f"{pd}/tst_both_dir/both_file1",
            f"{pd}/tst_both_dir/both_file2",
            f"{pd}/tst_both_dir/both_subdir",
            f"{pd}/tst_both_dir/both_subdir/both_file3",
            f"{pd}/tst_standby_dir",
            f"{pd}/tst_standby_dir/standby_file1",
            f"{pd}/tst_standby_dir/standby_file2",
            f"{pd}/tst_standby_dir/standby_file3 with 'quotes'",
            f"{pd}/tst_standby_dir/standby_subdir",
            f"{pd}/tst_standby_dir/standby_subdir/standby_file4",
        ]


def test_growing_files(pg_install_dir, rewind_driver):
    with rewind_driver() as rw:
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


class SymlinkWalDriver(TdeRewindDriver):
    def __init__(self, *args, xlogdir, **kw):
        super().__init__(*args, **kw)
        self.xlogdir = xlogdir

    def configure_primary(self, primary):
        super().configure_primary(primary)
        primary.stop()
        wal = primary.datadir / "pg_wal"
        shutil.move(wal, self.xlogdir)
        wal.symlink_to(self.xlogdir, target_is_directory=True)
        primary.start()


# pg_tde_rewind when the target's pg_wal directory is a symlink.
@pytest.mark.parametrize("mode", ["local", "remote"])
def test_pg_xlog_symlink(mode, pg_install_dir, sw_log_dir, node_config, keyring_obj, tmp_path):
    with SymlinkWalDriver(
        pg_install_dir,
        cipher="aes_128",
        keyring=keyring_obj,
        debug=True,
        config=node_config,
        xlogdir=tmp_path / "xlog_primary",
    ) as rw:
        p = rw.setup_primary()
        assert (p.datadir / "pg_wal").is_symlink()

        p.safe_sql("CREATE TABLE tbl1 (d text)")
        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary')")
        p.safe_sql("CHECKPOINT")

        s = rw.create_standby()

        p.safe_sql("INSERT INTO tbl1 values ('in primary, before promotion')")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        p.safe_sql("INSERT INTO tbl1 VALUES ('in primary, after promotion')")
        s.safe_sql("INSERT INTO tbl1 VALUES ('in standby, after promotion')")

        rw.run_rewind(mode)

        assert p.safe_sql("SELECT * FROM tbl1") == [
            ["in primary"],
            ["in primary, before promotion"],
            ["in standby, after promotion"],
        ]
