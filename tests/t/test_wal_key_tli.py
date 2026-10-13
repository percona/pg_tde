import pytest

from pgtde.rewind import run_databases


@pytest.mark.bug("PG-1813")
def test_wal_key_tli(pg_install_dir, sw_log_dir, node_config, keyring_obj):
    run_databases(pg_install_dir, "remote", keyring_obj, restart_standby=True, config=node_config)
