from pathlib import Path
from typing import override

import stormweaver.testing as st
from stormweaver.keyrings.base import Keyring
from stormweaver.testing import PgTestNode
from stormweaver.testing.rewind import RewindDriver

from pgtde import api
from pgtde.node import TdeNode

ALL_MODES = [("local", "aes_128"), ("remote", "aes_128"), ("archive", "aes_128"), ("local", "aes_256")]

REWIND_USER_SQL = """
CREATE ROLE rewind_user LOGIN;
GRANT EXECUTE ON function pg_catalog.pg_ls_dir(text, boolean, boolean) TO rewind_user;
GRANT EXECUTE ON function pg_catalog.pg_stat_file(text, boolean) TO rewind_user;
GRANT EXECUTE ON function pg_catalog.pg_read_binary_file(text) TO rewind_user;
GRANT EXECUTE ON function
    pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean) TO rewind_user;
"""


class TdeRewindDriver(RewindDriver):
    """RewindTest.pm: encrypted WAL, tde_heap default, pg_tde_rewind."""

    node_cls = TdeNode
    rewind_bin = "pg_tde_rewind"

    def __init__(
        self,
        install_dir: str | Path,
        *,
        cipher: str,
        keyring: Keyring,
        debug: bool = False,
        initdb_extra: list[str] | None = None,
        config: dict[str, str] | None = None,
    ) -> None:
        super().__init__(install_dir, debug=debug)
        self.cipher = cipher
        self.keyring = keyring
        self.initdb_extra = initdb_extra or []
        self.config = config or {}
        self.backup_options: tuple[str, ...] = ()

    @override
    def primary_config(self) -> dict[str, str]:
        # cipher must be set before key creation
        return (
            super().primary_config() | {"allow_in_place_tablespaces": "on", "pg_tde.cipher": self.cipher} | self.config
        )

    @override
    def initdb_args(self) -> list[str] | None:
        return ["--data-checksums", *self.initdb_extra]

    @override
    def rewind_user(self) -> str | None:
        return "rewind_user"

    @override
    def configure_primary(self, primary: PgTestNode) -> None:
        assert isinstance(primary, TdeNode)
        api.create_extension(primary)
        api.add_provider(primary, self.keyring, "file-keyring-wal", scope="global")
        api.create_key(primary, "global-db-principal-key", "file-keyring-wal", scope="global")
        api.set_server_key(primary, "global-db-principal-key", "file-keyring-wal")
        api.add_provider(primary, self.keyring, "file-keyring")
        api.create_key(primary, "test-db-key", "file-keyring")
        api.set_key(primary, "test-db-key", "file-keyring")
        primary.db.add_config({"pg_tde.wal_encrypt": "on", "default_table_access_method": "tde_heap"})
        primary.restart()
        primary.safe_sql(REWIND_USER_SQL)

    @override
    def backup_primary(self) -> Path:
        assert isinstance(self.primary, TdeNode)
        dest = self.primary.tde_basebackup(None, "-X", "stream", *self.backup_options)
        return dest

    @override
    def create_standby(self, *backup_options: str) -> PgTestNode:
        self.backup_options = backup_options
        return super().create_standby()


def run_databases(
    install_dir: str | Path,
    mode: str,
    keyring: Keyring,
    *,
    restart_standby: bool = False,
    config: dict[str, str] | None = None,
) -> None:
    with TdeRewindDriver(
        install_dir, cipher="aes_128", keyring=keyring, debug=True, initdb_extra=["-g"], config=config
    ) as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE DATABASE inprimary")
        with p.connect(db="inprimary") as c:
            c.safe_sql("CREATE TABLE inprimary_tab (a int) USING heap")

        s = rw.create_standby()
        if restart_standby:
            # new WAL key at the same start LSN, other TLI after rewind
            s.restart()

        p.safe_sql("CREATE DATABASE beforepromotion")
        with p.connect(db="beforepromotion") as c:
            c.safe_sql("CREATE TABLE beforepromotion_tab (a int) USING heap")

        rw.promote_standby()

        p.safe_sql("CREATE DATABASE primary_afterpromotion")
        with p.connect(db="primary_afterpromotion") as c:
            c.safe_sql("CREATE TABLE primary_promotion_tab (a int) USING heap")
        s.safe_sql("CREATE DATABASE standby_afterpromotion")
        with s.connect(db="standby_afterpromotion") as c:
            c.safe_sql("CREATE TABLE standby_promotion_tab (a int) USING heap")

        rw.run_rewind(mode)

        assert [r[0] for r in p.safe_sql("SELECT datname FROM pg_database ORDER BY 1")] == [
            "beforepromotion",
            "inprimary",
            "postgres",
            "standby_afterpromotion",
            "template0",
            "template1",
        ]
        assert st.check_mode_recursive(p.datadir, 0o750, 0o640) == []


def create_tail_block(p: PgTestNode, tablespace: str | None = None) -> None:
    ts = f" TABLESPACE {tablespace}" if tablespace else ""
    for t in ("tail_t", "block_t"):
        p.safe_sql(
            f"CREATE TABLE {t} (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap{ts}"
        )
        p.safe_sql(f"INSERT INTO {t} (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
    p.safe_sql("CHECKPOINT")


def diverge_tail_block(p: PgTestNode, s: PgTestNode) -> None:
    # changed blocks on the old primary, appended blocks on the new one
    p.safe_sql("UPDATE block_t SET f1='YYYYYYY' WHERE id % 10 = 0")
    s.safe_sql("INSERT INTO tail_t (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)")
    s.safe_sql("CHECKPOINT")


def check_tail_block(p: PgTestNode) -> None:
    assert p.sql_value("SELECT count(*) FROM tail_t") == "2000"
    assert p.sql_value("SELECT count(*) FROM block_t") == "1000"
