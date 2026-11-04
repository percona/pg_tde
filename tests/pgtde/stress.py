from pathlib import Path
from typing import Any

from stormweaver import scenario
from stormweaver.keyrings.base import Keyring
from stormweaver.keyrings.file import FileKeyring

from pgtde.providers import add_provider_sql


def _execute(conn: Any, query: str) -> None:
    result = conn.execute(query)
    if not result.success():
        raise RuntimeError(f"pg_tde setup failed: {query}: {result.error_message}")


def init_tde_only_for_db(conn: Any, keyring: Keyring) -> None:
    _execute(conn, "CREATE EXTENSION IF NOT EXISTS pg_tde;")
    _execute(conn, add_provider_sql(keyring, "database", "reg_file") + ";")
    _execute(conn, "SELECT pg_tde_create_key_using_database_key_provider('principal-key', 'reg_file');")
    _execute(conn, "SELECT pg_tde_set_key_using_database_key_provider('principal-key', 'reg_file');")


def init_tde_globally(conn: Any, keyring: Keyring) -> None:
    _execute(conn, "CREATE EXTENSION IF NOT EXISTS pg_tde;")
    _execute(conn, add_provider_sql(keyring, "global", "reg_file") + ";")
    _execute(conn, "SELECT pg_tde_create_key_using_global_key_provider('server-principal-key', 'reg_file');")
    _execute(conn, "SELECT pg_tde_set_key_using_global_key_provider('server-principal-key', 'reg_file');")
    _execute(conn, "SELECT pg_tde_set_server_key_using_global_key_provider('server-principal-key', 'reg_file');")
    _execute(conn, "SELECT pg_tde_create_key_using_global_key_provider('def-principal-key', 'reg_file');")
    _execute(conn, "SELECT pg_tde_set_default_key_using_global_key_provider('def-principal-key', 'reg_file');")
    _execute(conn, "ALTER SYSTEM SET pg_tde.wal_encrypt = ON;")


def tde_options(parser: Any) -> None:
    parser.add_argument("--tde", choices=["on", "on_wal", "off"], default="on")


def single_pg_tde(opts: Any, *, datadir_name: str = "primary", **kw: Any) -> Any:
    if opts.tde == "off":
        return scenario.single_pg(opts, datadir_name=datadir_name, **kw)
    datadir = Path(opts.config.datadir(datadir_name)).resolve()
    keyring = FileKeyring(datadir.parent / f"{datadir.name}_keyring.per")
    keyring.path.parent.mkdir(parents=True, exist_ok=True)
    keyring.path.unlink(missing_ok=True)
    init = init_tde_only_for_db if opts.tde == "on" else init_tde_globally
    return scenario.single_pg(
        opts,
        preload=["pg_tde"],
        access_methods=["tde_heap", "heap"],
        db_init=lambda conn: init(conn, keyring),
        datadir_name=datadir_name,
        **kw,
    )
