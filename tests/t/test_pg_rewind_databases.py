import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import run_databases


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_pg_rewind_databases(mode, pg_install_dir, sw_log_dir, tmp_path):
    run_databases(pg_install_dir, mode, FileKeyring(tmp_path / "kr.per"))
