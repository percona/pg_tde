import tarfile
from pathlib import Path

import pytest

from pgtde.node import TdeNode

# datadir made with pg_tde 2.1.1 on PG18: encrypted WAL, encrypted table, kill -9
pytestmark = [pytest.mark.pg_min(18), pytest.mark.pg_max(18)]

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "keys_update_datadir.tar.gz"


def test_keys_from_2_1_1(pg_install_dir, sw_log_dir, tmp_path):
    datadir = tmp_path / "keysupdate"
    datadir.mkdir()
    with tarfile.open(FIXTURE) as tar:
        tar.extractall(datadir, filter="data")
    datadir.chmod(0o700)
    (datadir / "postmaster.pid").unlink(missing_ok=True)

    # tcp only, tmp_path can exceed the unix socket path limit
    with TdeNode.adopt(pg_install_dir, datadir, name="keysupdate", unix_socket=False) as node:
        node.start()
        # stderr skipped, collation version mismatch warnings depend on the host
        cp = node.tool("psql", "-X", "-q", "-A", "-t", "-U", "vagrant", "-c", "table test_enc")
        assert cp.returncode == 0, cp.stderr
        assert cp.stdout.strip() == "1\n2"
