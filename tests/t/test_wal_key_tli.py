import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import run_databases


@pytest.mark.bug("PG-1813")
def test_wal_key_tli(pg_install_dir, sw_log_dir, tmp_path):
    run_databases(pg_install_dir, "remote", FileKeyring(tmp_path / "kr.per"), restart_standby=True)
