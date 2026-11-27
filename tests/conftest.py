import contextlib
import hashlib
import itertools
import re
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from stormweaver import keyrings
from stormweaver.matrix import register_dimension
from stormweaver.testing import InjectionPoints

from pgtde.node import TdeNode


def pytest_configure(config: pytest.Config) -> None:
    # selected with the generic matrix options: --matrix keyring=vault,kmip or --all-values
    register_dimension(config, "keyring", default="file", available=keyrings.selected_keyrings, indirect=True)


@pytest.fixture
def keyring(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[keyrings.Keyring]:
    """Keyring of the current matrix value (file, vault, kmip)."""
    with keyrings.open_keyring(request.param, tmp_path / "keyring") as kr:
        yield kr


@pytest.fixture
def make_keyring(keyring: keyrings.Keyring, tmp_path: Path) -> Iterator[Callable[[], keyrings.Keyring]]:
    """A new, independent keyring of the current matrix kind on every call, closed at teardown.

    Only file keyrings are independent: vault and kmip return the test's keyring.
    """
    with contextlib.ExitStack() as stack:
        n = itertools.count(1)

        def make() -> keyrings.Keyring:
            if keyring.kind != "file":
                return keyring
            return stack.enter_context(keyrings.open_keyring("file", tmp_path / f"keyring-{next(n)}"))

        yield make


def _node_name(request: pytest.FixtureRequest) -> str:
    # the name ends up in the unix socket path twice, keep it short; the hash
    # keeps parametrized cases with a long common prefix apart
    short = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)[:22]
    digest = hashlib.sha1(request.node.nodeid.encode()).hexdigest()[:6]
    return f"{short}-{digest}"


@pytest.fixture
def tde_node(pg_install_dir: str, sw_log_dir: Path, request: pytest.FixtureRequest) -> Iterator[TdeNode]:
    """Server with pg_tde preloaded, extension not created."""
    # sw_log_dir: server logs go to the run's log dir
    with TdeNode.fresh(pg_install_dir, name=_node_name(request)) as node:
        yield node


@pytest.fixture
def key_name() -> Callable[[str], str]:
    """key_name("db-key") -> "<prefix>-db-key", the prefix unique to this test.

    vault and kmip stores outlive the test and are shared with parallel runs.
    """
    prefix = uuid.uuid4().hex[:8]
    return lambda name: f"{prefix}-{name}"


@pytest.fixture
def tde_node_with_key(tde_node: TdeNode, keyring: keyrings.Keyring, key_name: Callable[[str], str]) -> TdeNode:
    """tde_node ready for tde_heap tables: extension, database provider, principal key."""
    tde = tde_node.tde
    tde.create_extension()
    tde.add_provider("db-provider", keyring)
    tde.create_key(key_name("db-key"), "db-provider")
    tde.set_key(key_name("db-key"), "db-provider")
    return tde_node


@pytest.fixture
def make_standby() -> Iterator[Callable[..., TdeNode]]:
    """Streaming standbys from a base backup of the given primary, stopped at teardown."""
    with contextlib.ExitStack() as stack:

        def make(primary: TdeNode, name: str = "standby") -> TdeNode:
            return stack.enter_context(TdeNode.from_backup(primary.basebackup(), primary, name=name))

        yield make


@pytest.fixture
def injection_points(tde_node: TdeNode) -> InjectionPoints:
    # pg_tde can wait at a point with its key lock held, which blocks catalog reads in
    # databases with a key map; template1 has none
    ip = InjectionPoints(tde_node, poll_db="template1")
    if not ip.available():
        pytest.skip("injection points not available (server build option or injection_points module)")
    return ip
