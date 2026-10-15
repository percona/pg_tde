import subprocess
from pathlib import Path
from typing import override

import stormweaver.testing as st
from stormweaver.keyrings.base import Keyring
from stormweaver.testing import PgTestNode
from stormweaver.testing.rewind import RewindDriver

from pgtde import api
from pgtde.node import TdeNode
from pgtde.wal import archive_all

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
        wal_encrypt: bool = True,
    ) -> None:
        super().__init__(install_dir, debug=debug)
        self.cipher = cipher
        self.keyring = keyring
        self.wal_encrypt = wal_encrypt
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
        api.add_provider(primary, self.keyring, "wal-provider", scope="global")
        api.create_key(primary, "global-db-principal-key", "wal-provider", scope="global")
        api.set_server_key(primary, "global-db-principal-key", "wal-provider")
        api.add_provider(primary, self.keyring, "db-provider")
        api.create_key(primary, "test-db-key", "db-provider")
        api.set_key(primary, "test-db-key", "db-provider")
        primary.db.add_config(
            {"pg_tde.wal_encrypt": "on" if self.wal_encrypt else "off", "default_table_access_method": "tde_heap"}
        )
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

    def rewind(
        self, *, source: str = "local", restore: bool = False, config_file: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        # pg_tde_rewind of the primary from the standby, the caller stops and starts the nodes
        assert isinstance(self.primary, TdeNode) and self.standby is not None
        p, s = self.primary, self.standby
        if source == "local":
            src = f"--source-pgdata={s.datadir}"
        else:
            src = f"--source-server=host=localhost port={s.port} dbname=postgres user={self.rewind_user()}"
        args: list[str | Path] = [self.rewind_bin, "--debug", src, f"--target-pgdata={p.datadir}", "--no-sync"]
        if restore:
            args.append("--restore-target-wal")
        if config_file is not None:
            args.append(f"--config-file={config_file}")
        return p.tool(*args)

    @override
    def run_rewind(self, mode: str) -> None:
        if mode != "restore":
            super().run_rewind(mode)
            return
        # local source, target WAL recycled since the divergence comes from the
        # target's own restore_command; needs archiving and wal_keep_size=0
        assert isinstance(self.primary, TdeNode) and self.standby is not None
        p, s = self.primary, self.standby
        archive_all(p)
        archive_all(p)
        p.safe_sql("CHECKPOINT")
        p.stop()
        with p.db.preserve_config() as conf:
            s.stop()
            cp = self.rewind(restore=True, config_file=conf)
            st.command_ok(cp, f"{self.rewind_bin} restore")
        assert "restored from archive" in cp.stderr, cp.stderr
        s.start()
        p.rejoin_as_standby(s)
        s.wait_for_catchup(p)

    def swap_roles(self) -> None:
        # the rewound node becomes the standby to promote next
        self.primary, self.standby = self.standby, self.primary


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


def create_asymmetric_tables(p: PgTestNode, s: PgTestNode) -> None:
    # after promotion: one table only on the new primary, one only on the old
    s.safe_sql("CREATE TABLE source_only (id int) USING tde_heap; INSERT INTO source_only VALUES (1), (2)")
    p.safe_sql("CREATE TABLE target_only (id int) USING tde_heap; INSERT INTO target_only VALUES (10), (20)")


def check_asymmetric_tables(p: PgTestNode) -> None:
    assert p.sql_value("SELECT count(*) FROM source_only") == "2"
    assert p.sql_value("SELECT to_regclass('target_only')") is None
