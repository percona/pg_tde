from pathlib import Path
from typing import Any

from stormweaver.keyrings.base import Keyring
from stormweaver.keyrings.file import FileKeyring

from pgtde.providers import Scope, add_provider_sql


def _q(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def create_extension(node: Any, schema: str | None = None) -> None:
    sql = "CREATE EXTENSION IF NOT EXISTS pg_tde"
    if schema:
        sql += f" SCHEMA {schema}"
    node.safe_sql(sql)


def drop_extension(node: Any, cascade: bool = False) -> None:
    node.safe_sql("DROP EXTENSION pg_tde" + (" CASCADE" if cascade else ""))


def create_key(node: Any, key: str, provider: str, *, scope: Scope = "database") -> None:
    node.safe_sql(f"SELECT pg_tde_create_key_using_{scope}_key_provider({_q(key)}, {_q(provider)})")


def set_key(node: Any, key: str, provider: str, *, scope: Scope = "database") -> None:
    node.safe_sql(f"SELECT pg_tde_set_key_using_{scope}_key_provider({_q(key)}, {_q(provider)})")


def set_server_key(node: Any, key: str, provider: str) -> None:
    node.safe_sql(f"SELECT pg_tde_set_server_key_using_global_key_provider({_q(key)}, {_q(provider)})")


def set_default_key(node: Any, key: str, provider: str) -> None:
    node.safe_sql(f"SELECT pg_tde_set_default_key_using_global_key_provider({_q(key)}, {_q(provider)})")


def delete_key(node: Any) -> None:
    node.safe_sql("SELECT pg_tde_delete_key()")


def delete_default_key(node: Any) -> None:
    node.safe_sql("SELECT pg_tde_delete_default_key()")


def add_provider(node: Any, keyring: Keyring | str | Path, name: str, *, scope: Scope = "database") -> None:
    if not isinstance(keyring, Keyring):
        keyring = FileKeyring(Path(keyring))
    node.safe_sql(add_provider_sql(keyring, scope, name))


def delete_provider(node: Any, name: str, *, scope: Scope = "database") -> None:
    node.safe_sql(f"SELECT pg_tde_delete_{scope}_key_provider({_q(name)})")


def change_provider_file(node: Any, name: str, path: str, *, scope: Scope = "database") -> None:
    node.safe_sql(f"SELECT pg_tde_change_{scope}_key_provider_file({_q(name)}, {_q(path)})")


def list_providers(node: Any, *, scope: Scope = "database") -> list[list[str | None]]:
    return node.safe_sql(f"SELECT id, name, type, options FROM pg_tde_list_all_{scope}_key_providers() ORDER BY id")


def _info_row(rows: list[list[str | None]]) -> list[str | None] | None:
    if not rows or all(v is None for v in rows[0]):
        return None
    return rows[0]


def _key_info(node: Any, fn: str) -> list[str | None] | None:
    return _info_row(node.safe_sql(f"SELECT provider_id, provider_name, key_name FROM {fn}()"))


def key_info(node: Any) -> list[str | None] | None:
    return _key_info(node, "pg_tde_key_info")


def server_key_info(node: Any) -> list[str | None] | None:
    return _key_info(node, "pg_tde_server_key_info")


def default_key_info(node: Any) -> list[str | None] | None:
    return _key_info(node, "pg_tde_default_key_info")


def verify_key(node: Any) -> None:
    node.safe_sql("SELECT pg_tde_verify_key()")


def verify_server_key(node: Any) -> None:
    node.safe_sql("SELECT pg_tde_verify_server_key()")


def verify_default_key(node: Any) -> None:
    node.safe_sql("SELECT pg_tde_verify_default_key()")


def is_encrypted(node: Any, rel: str) -> bool | None:
    v = node.sql_value(f"SELECT pg_tde_is_encrypted({_q(rel)})")
    return None if v is None else v == "t"


def version(node: Any) -> str:
    v = node.sql_value("SELECT pg_tde_version()")
    assert v is not None
    return v


def set_wal_encrypt(node: Any, on: bool) -> None:
    node.safe_sql(f"ALTER SYSTEM SET pg_tde.wal_encrypt = {'on' if on else 'off'}")


def has_function(node: Any, name: str) -> bool:
    q = "SELECT count(*) > 0 FROM pg_proc WHERE proname = $1"
    return node.sql_value(q, (name,)) == "t"


def require_contrib(node: Any, name: str) -> None:
    import pytest

    q = "SELECT count(*) FROM pg_available_extensions WHERE name = $1"
    if node.sql_value(q, (name,)) == "0":
        pytest.skip(f"contrib module {name} not installed")
