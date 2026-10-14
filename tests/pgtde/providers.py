from typing import Literal

from stormweaver.keyrings.base import Keyring
from stormweaver.keyrings.file import FileKeyring
from stormweaver.keyrings.kmip import KmipKeyring
from stormweaver.keyrings.vault import VaultKeyring

from pgtde.sql import sql_literal

Scope = Literal["global", "database"]
# oid global providers are stored under
GLOBAL_OID = "1664"


def add_provider_sql(keyring: Keyring, scope: Scope, name: str) -> str:
    """SELECT statement registering keyring as a pg_tde key provider."""
    return _provider_sql("add", keyring, scope, name)


def change_provider_sql(keyring: Keyring, scope: Scope, name: str) -> str:
    """SELECT statement pointing provider name at keyring."""
    return _provider_sql("change", keyring, scope, name)


def _provider_sql(op: str, keyring: Keyring, scope: Scope, name: str) -> str:
    if scope not in ("global", "database"):
        raise ValueError(f"unknown scope: {scope}")
    args: list[str | int]
    if isinstance(keyring, FileKeyring):
        suffix = "file"
        args = [name, str(keyring.path)]
    elif isinstance(keyring, VaultKeyring):
        suffix = "vault_v2"
        args = [name, keyring.url, keyring.mount_path, str(keyring.token_file), str(keyring.ca_cert)]
        if keyring.namespace:
            args.append(keyring.namespace)
    elif isinstance(keyring, KmipKeyring):
        suffix = "kmip"
        args = [
            name,
            keyring.host,
            keyring.port,
            str(keyring.client_cert),
            str(keyring.client_key),
            str(keyring.ca_cert),
        ]
    else:
        raise TypeError(f"unsupported keyring: {type(keyring).__name__}")
    fn = f"pg_tde_{op}_{scope}_key_provider_{suffix}"
    return f"SELECT {fn}({', '.join(sql_literal(a) for a in args)})"
