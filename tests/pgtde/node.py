from pathlib import Path
from typing import Any, Self

from stormweaver.testing import PgTestNode, TestConn

from pgtde.tde import Tde


class TdeConn(TestConn):
    @property
    def tde(self) -> Tde:
        return Tde(self)


class TdeNode(PgTestNode):
    @classmethod
    def fresh(
        cls, install_dir: str | Path, *, name: str = "node", config: dict[str, str] | None = None, **kw: Any
    ) -> Self:
        # fsync off like PostgreSQL::Test::Cluster: a crashed cluster
        # otherwise spends ~10s syncing the whole datadir before recovery
        cfg = {"fsync": "off", "shared_preload_libraries": "pg_tde"} | (config or {})
        return super().fresh(install_dir, name=name, config=cfg, **kw)

    @property
    def tde(self) -> Tde:
        return Tde(self)

    def connect(self, db: str | None = None, log_name: str | None = None) -> TdeConn:
        conn = super().connect(db, log_name)
        return TdeConn(conn.raw, name=conn.name, node=self)
