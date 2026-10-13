import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Self

from stormweaver.backends.postgres import Postgres
from stormweaver.keyrings.base import Keyring
from stormweaver.testing import PgTestNode, alloc_port, ensure_logging

from pgtde import api


def _base_config(preload: str | None, config: dict[str, str] | None) -> dict[str, str]:
    # fsync off like PostgreSQL::Test::Cluster: a crashed --no-sync cluster
    # otherwise spends ~10s syncing the whole datadir before recovery
    cfg = {"fsync": "off"}
    if preload:
        cfg["shared_preload_libraries"] = preload
    return cfg | (config or {})


class TdeNode(PgTestNode):
    @classmethod
    def fresh(
        cls,
        install_dir: str | Path,
        *,
        name: str = "node",
        config: dict[str, str] | None = None,
        preload: str | None = "pg_tde",
        **kw: Any,
    ) -> Self:
        return super().fresh(install_dir, name=name, config=_base_config(preload, config), **kw)

    @classmethod
    def unstarted(
        cls,
        install_dir: str | Path,
        *,
        name: str,
        config: dict[str, str] | None = None,
        preload: str | None = "pg_tde",
        initdb_args: list[str] | None = None,
    ) -> Self:
        # initdb only, the caller starts it (or hands it to pg_upgrade)
        ensure_logging()
        base = Path(tempfile.mkdtemp(prefix=f"sw-{name}-", dir="/tmp"))
        try:
            pg = Postgres(install_dir, base / name, port=alloc_port(), initdb_args=initdb_args)
        except BaseException:
            shutil.rmtree(base, ignore_errors=True)
            raise
        node = cls(pg, "postgres", name)
        node._owned_dir = base
        try:
            pg.add_config(_base_config(preload, config))
        except BaseException:
            node.close()
            raise
        node._node_event("init")
        return node

    @classmethod
    def adopt(
        cls,
        install_dir: str | Path,
        datadir: Path,
        *,
        name: str,
        config: dict[str, str] | None = None,
        unix_socket: bool = True,
    ) -> Self:
        # existing datadir (backup, fixture tarball), not started
        ensure_logging()
        port = alloc_port()
        pg = Postgres(install_dir, datadir, init=False, port=port)
        sockdir = str(datadir.resolve().parent) if unix_socket else ""
        pg.add_config({"port": str(port), "unix_socket_directories": sockdir})
        if config:
            pg.add_config(config)
        node = cls(pg, "postgres", name)
        node._node_event("init")
        return node

    def setup_db_key(
        self, keyring: Keyring | str | Path, *, provider: str = "file-vault", key: str = "test-db-key"
    ) -> None:
        api.create_extension(self)
        api.add_provider(self, keyring, provider)
        api.create_key(self, key, provider)
        api.set_key(self, key, provider)

    def setup_server_key(
        self,
        keyring: Keyring | str | Path,
        *,
        provider: str = "global-vault",
        key: str = "server-key",
        wal_encrypt: bool = False,
    ) -> None:
        api.create_extension(self)
        api.add_provider(self, keyring, provider, scope="global")
        api.create_key(self, key, provider, scope="global")
        api.set_server_key(self, key, provider)
        if wal_encrypt:
            api.set_wal_encrypt(self, True)

    def setup_default_key(
        self, keyring: Keyring | str | Path, *, provider: str = "global-vault", key: str = "default-key"
    ) -> None:
        api.create_extension(self)
        api.add_provider(self, keyring, provider, scope="global")
        api.create_key(self, key, provider, scope="global")
        api.set_default_key(self, key, provider)

    def is_encrypted(self, rel: str) -> bool | None:
        return api.is_encrypted(self, rel)

    def assert_not_on_disk(self, table: str, needle: str | bytes) -> None:
        want = needle.encode() if isinstance(needle, str) else needle
        assert want not in self.read_relation_file(table), f"{needle!r} found on disk in {table}"

    def assert_on_disk(self, table: str, needle: str | bytes) -> None:
        want = needle.encode() if isinstance(needle, str) else needle
        assert want in self.read_relation_file(table), f"{needle!r} not found on disk in {table}"

    def tool(self, name: str, *args: str | Path, **kw: Any) -> subprocess.CompletedProcess[str]:
        return self.run_bin(name, *args, **kw)

    def tde_basebackup(self, dest: Path | None = None, *extra: str) -> Path:
        # -E needs the keys up front, pre-copy pg_tde/ like pgtde.pm backup() did
        if dest is None:
            dest = Path(tempfile.mkdtemp(prefix="sw-backup-", dir="/tmp")) / "data"
        dest.mkdir(parents=True, exist_ok=True)
        dest.chmod(self.datadir.stat().st_mode & 0o777)
        shutil.copytree(self.datadir / "pg_tde", dest / "pg_tde", dirs_exist_ok=True)
        cp = self.tool("pg_tde_basebackup", "-D", dest, "--checkpoint", "fast", "--no-sync", "-E", *extra)
        if cp.returncode != 0:
            raise RuntimeError(f"pg_tde_basebackup failed: {cp.stderr}")
        return dest
