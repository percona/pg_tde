# pg_tde_rewind when the target's pg_wal directory is a symlink.
import shutil

import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import TdeRewindDriver


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


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_pg_rewind_pg_xlog_symlink(mode, pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with SymlinkWalDriver(
        pg_install_dir, cipher="aes_128", keyring=kr, debug=True, xlogdir=tmp_path / "xlog_primary"
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
