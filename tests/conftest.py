import hashlib
import os
import re
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from stormweaver import keyrings, pginstall
from stormweaver.keyrings.file import FileKeyring
from stormweaver.matrix import register_dimension
from stormweaver.testing import process

sys.path.insert(0, str(Path(__file__).parent))

from pgtde.node import TdeNode  # noqa: E402

CIPHERS = ["aes_128", "aes_256"]
IO_METHODS = ["worker", "sync", "io_uring"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--keyrings",
        default=os.environ.get("PG_TDE_TEST_KEYRINGS"),
        help="comma separated keyring kinds for the keyring dimension",
    )
    parser.addoption(
        "--io-methods",
        default=os.environ.get("PG_TDE_TEST_IO_METHODS"),
        help="comma separated io_method values (PG18+)",
    )
    parser.addoption("--ciphers", default=os.environ.get("PG_TDE_TEST_CIPHERS"), help="comma separated cipher values")
    parser.addoption(
        "--old-pg-config",
        default=os.environ.get("PG_TDE_TEST_OLD_PG_CONFIG"),
        help="pg_config of an older installation, for upgrade tests",
    )


def _csv(config: pytest.Config, opt: str) -> list[str] | None:
    v = config.getoption(opt)
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


_INSTALL = pytest.StashKey[pginstall.PgInstall | None]()


def _install(config: pytest.Config) -> pginstall.PgInstall | None:
    if _INSTALL not in config.stash:
        try:
            config.stash[_INSTALL] = pginstall.resolve(config.getoption("--pg-config"))
        except RuntimeError as e:
            raise pytest.UsageError(str(e)) from e
    return config.stash[_INSTALL]


def _io_methods(config: pytest.Config) -> list[str]:
    explicit = _csv(config, "--io-methods")
    if explicit:
        return explicit
    pi = _install(config)
    if pi is None or pi.major is None or pi.major < 18:
        return ["default"]
    return ["default", *IO_METHODS]


def pytest_configure(config: pytest.Config) -> None:
    register_dimension(
        config, "keyring", default="file", available=lambda: _csv(config, "--keyrings") or keyrings.selected_keyrings()
    )
    register_dimension(config, "io_method", default="default", available=lambda: _io_methods(config))
    register_dimension(config, "cipher", default="aes_128", available=lambda: _csv(config, "--ciphers") or CIPHERS)


def _skip(item: pytest.Item, reason: str) -> None:
    item.add_marker(pytest.mark.skip(reason=reason))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    pi = _install(config)
    major = pi.major if pi else None
    avail: list[str] | None = None
    for item in items:
        for m in item.iter_markers("pg_min"):
            if major is not None and major < m.args[0]:
                _skip(item, f"needs PostgreSQL >= {m.args[0]}")
        for m in item.iter_markers("pg_max"):
            if major is not None and major > m.args[0]:
                _skip(item, f"needs PostgreSQL <= {m.args[0]}")
        if item.get_closest_marker("linux_only") and sys.platform != "linux":
            _skip(item, "Linux only")
        for kind in ("vault", "kmip"):
            if item.get_closest_marker(f"needs_{kind}"):
                if avail is None:
                    avail = keyrings.available_keyrings()
                if kind not in avail:
                    _skip(item, f"{kind} keyring service not available")
        if item.get_closest_marker("needs_pgbackrest") and not shutil.which("pgbackrest"):
            _skip(item, "pgbackrest not on PATH")
        if item.get_closest_marker("needs_old_install") and not config.getoption("--old-pg-config"):
            _skip(item, "set --old-pg-config")


@pytest.fixture(scope="session")
def pg_major(pg_install: Any) -> int:
    assert pg_install.major is not None
    return int(pg_install.major)


@pytest.fixture
def file_keyring(tmp_path: Path) -> FileKeyring:
    return FileKeyring(tmp_path / "db.keys")


@pytest.fixture
def keyring_obj(keyring: str, tmp_path: Path) -> Iterator[keyrings.Keyring]:
    with keyrings.open_keyring(keyring, tmp_path / "keyring") as kr:
        yield kr


def _node_name(request: pytest.FixtureRequest) -> str:
    # the name ends up in the unix socket path twice, keep it short; the hash
    # keeps parametrized cases with a long common prefix apart
    short = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)[:22]
    digest = hashlib.sha1(request.node.nodeid.encode()).hexdigest()[:6]
    return f"{short}-{digest}"


def _node_config(request: pytest.FixtureRequest) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if "cipher" in request.fixturenames:
        cfg["pg_tde.cipher"] = request.getfixturevalue("cipher")
    if "io_method" in request.fixturenames:
        io_method = request.getfixturevalue("io_method")
        if io_method != "default":
            cfg["io_method"] = io_method
    return cfg


@pytest.fixture
def tde_node(pg_install_dir: str, sw_log_dir: Path, request: pytest.FixtureRequest) -> Iterator[TdeNode]:
    with TdeNode.fresh(pg_install_dir, name=_node_name(request), config=_node_config(request)) as node:
        yield node


@pytest.fixture
def tde_node_db(tde_node: TdeNode, file_keyring: FileKeyring) -> TdeNode:
    tde_node.setup_db_key(file_keyring)
    return tde_node


@pytest.fixture
def tde_node_global(tde_node: TdeNode, tmp_path: Path) -> TdeNode:
    tde_node.setup_server_key(FileKeyring(tmp_path / "global.keys"), wal_encrypt=True)
    tde_node.restart()
    return tde_node


class Tools:
    def __init__(self, install_dir: str) -> None:
        self.install_dir = install_dir

    def run(self, name: str, *args: str | Path, **kw: Any) -> Any:
        return process.run_bin(self.install_dir, name, *args, **kw)

    def help_ok(self, name: str) -> None:
        process.program_help_ok(self.install_dir, name)

    def version_ok(self, name: str) -> None:
        process.program_version_ok(self.install_dir, name)

    def options_ok(self, name: str) -> None:
        process.program_options_handling_ok(self.install_dir, name)


@pytest.fixture
def tools(pg_install_dir: str) -> Tools:
    return Tools(pg_install_dir)
