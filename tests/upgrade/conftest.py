import tempfile

import pytest


@pytest.fixture
def socketdir():
    # tmp_path may be too long for a unix socket path
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        yield d


@pytest.fixture
def workdir(tmp_path):
    # pg_upgrade drops delete_old_cluster.sh and logs into its cwd
    d = tmp_path / "work"
    d.mkdir()
    return d
