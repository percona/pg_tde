import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from stormweaver import keyrings, pginstall
from stormweaver.keyrings.file import FileKeyring
from stormweaver.matrix import register_dimension
from stormweaver.testing import process

sys.path.insert(0, str(Path(__file__).parent))

from pgtde import upgrade as upgrade_mod  # noqa: E402
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
        action="append",
        default=[],
        help="pg_config of an older installation (or script:<cmd>), comma separated or repeated, for upgrade tests",
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


_UPGRADE = pytest.StashKey[list[upgrade_mod.UpgradeSource]]()


def _upgrade_sources(config: pytest.Config) -> list[upgrade_mod.UpgradeSource]:
    if _UPGRADE not in config.stash:
        values = list(config.getoption("--old-pg-config"))
        if not values and os.environ.get("PG_TDE_TEST_OLD_PG_CONFIG"):
            values = [os.environ["PG_TDE_TEST_OLD_PG_CONFIG"]]
        if any(upgrade_mod.is_script(v) for v in values) and config.getoption("numprocesses", None):
            raise pytest.UsageError("script: --old-pg-config entries change the install, they cannot run under xdist")
        pi = _install(config)
        if values and (pi is None or pi.pg_config is None):
            raise pytest.UsageError("--old-pg-config needs --pg-config")
        try:
            config.stash[_UPGRADE] = upgrade_mod.parse_sources(values, pi) if values else []
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as e:
            raise pytest.UsageError(f"--old-pg-config: {e}") from e
    return config.stash[_UPGRADE]


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


def pytest_report_header(config: pytest.Config) -> list[str]:
    srcs = _upgrade_sources(config)
    if not srcs:
        return []
    lines = ["old installs: " + ", ".join(f"{s.label} ({s.mode})" for s in srcs)]
    if any(not s.side_by_side for s in srcs):
        lines.append("script mode: only old_install tests run")
    return lines


def pytest_sessionstart(session: pytest.Session) -> None:
    # bad entries as a usage error, also under -q where the header is not built
    _upgrade_sources(session.config)


def pytest_unconfigure(config: pytest.Config) -> None:
    err: Exception | None = None
    for s in config.stash.get(_UPGRADE, []):
        try:
            s.switch_new()
        except Exception as e:
            err = err or e
    if err:
        raise err


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "upgrade" in metafunc.fixturenames:
        srcs = _upgrade_sources(metafunc.config)
        if srcs:
            metafunc.parametrize("upgrade", srcs, ids=[s.label for s in srcs], indirect=True)


def _skip(item: pytest.Item, reason: str) -> None:
    item.add_marker(pytest.mark.skip(reason=reason))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    pi = _install(config)
    major = pi.major if pi else None
    avail: list[str] | None = None
    for item in items:
        if "upgrade" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.old_install)
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
    srcs = _upgrade_sources(config)
    if any(not s.side_by_side for s in srcs):
        keep = [i for i in items if i.get_closest_marker("old_install")]
        drop = [i for i in items if not i.get_closest_marker("old_install")]
        if drop:
            config.hook.pytest_deselected(items=drop)
            items[:] = keep


@pytest.fixture
def upgrade(request: pytest.FixtureRequest) -> Iterator[upgrade_mod.UpgradeSource]:
    src = getattr(request, "param", None)
    if src is None:
        pytest.skip("set --old-pg-config")
    for m in request.node.iter_markers("old_install"):
        why = upgrade_mod.gate_mismatch(src, m.kwargs)
        if why:
            pytest.skip(why)
    try:
        yield src
    finally:
        src.switch_new()


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


def _marker_config(request: pytest.FixtureRequest) -> tuple[dict[str, str], list[str] | None]:
    cfg: dict[str, str] = {}
    initdb_args = None
    # iter_markers yields the closest first, apply it last
    for m in reversed(list(request.node.iter_markers("node_config"))):
        if m.args:
            cfg |= m.args[0]
        initdb_args = m.kwargs.get("initdb_args", initdb_args)
    return cfg, initdb_args


@pytest.fixture
def node_config(io_method: str, request: pytest.FixtureRequest) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if io_method != "default":
        cfg["io_method"] = io_method
    if "cipher" in request.fixturenames:
        cfg["pg_tde.cipher"] = request.getfixturevalue("cipher")
    return cfg | _marker_config(request)[0]


@pytest.fixture
def tde_node(
    pg_install_dir: str, sw_log_dir: Path, node_config: dict[str, str], request: pytest.FixtureRequest
) -> Iterator[TdeNode]:
    initdb_args = _marker_config(request)[1]
    with TdeNode.fresh(pg_install_dir, name=_node_name(request), config=node_config, initdb_args=initdb_args) as node:
        yield node


@pytest.fixture
def tde_node_factory(
    pg_install_dir: str, sw_log_dir: Path, node_config: dict[str, str], request: pytest.FixtureRequest
) -> Iterator[Callable[..., TdeNode]]:
    # nodes for multi-node tests, closed at teardown in reverse order
    with contextlib.ExitStack() as stack:

        def make(
            name: str,
            *,
            config: dict[str, str] | None = None,
            start: bool = True,
            install: pginstall.PgInstall | None = None,
            extra_initdb_args: list[str] | None = None,
            **kw: Any,
        ) -> TdeNode:
            cfg = node_config | (config or {})
            kw.setdefault("initdb_args", _marker_config(request)[1])
            if extra_initdb_args:
                kw["initdb_args"] = [*(kw["initdb_args"] or []), *extra_initdb_args]
            install_dir = pg_install_dir
            if install is not None:
                install_dir = str(install.install_dir)
                if install.major is not None and install.major < 18:
                    cfg.pop("io_method", None)
            if start:
                node = TdeNode.fresh(install_dir, name=name, config=cfg, **kw)
            else:
                node = TdeNode.unstarted(install_dir, name=name, config=cfg, **kw)
            return stack.enter_context(node)

        yield make


@pytest.fixture
def tde_node_db(keyring_obj: keyrings.Keyring, tde_node: TdeNode) -> TdeNode:
    tde_node.setup_db_key(keyring_obj)
    return tde_node


@pytest.fixture
def tde_node_global(keyring_obj: keyrings.Keyring, tde_node: TdeNode) -> TdeNode:
    tde_node.setup_server_key(keyring_obj, wal_encrypt=True)
    tde_node.restart()
    return tde_node


@pytest.fixture
def tde_node_default(keyring_obj: keyrings.Keyring, tde_node: TdeNode) -> TdeNode:
    tde_node.setup_default_key(keyring_obj)
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
