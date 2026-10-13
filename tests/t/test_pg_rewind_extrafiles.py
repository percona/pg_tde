# How pg_tde_rewind reacts to extra files and directories in the data dirs.
import sys

import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import TdeRewindDriver


def _put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(text)


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_pg_rewind_extrafiles(mode, pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher="aes_128", keyring=kr, debug=True) as rw:
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
