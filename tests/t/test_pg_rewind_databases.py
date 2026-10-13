import pytest

from pgtde.rewind import run_databases


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_pg_rewind_databases(mode, pg_install_dir, sw_log_dir, node_config, keyring_obj):
    run_databases(pg_install_dir, mode, keyring_obj, config=node_config)
