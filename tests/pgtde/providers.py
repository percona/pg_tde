from typing import Literal

from stormweaver.keyrings.base import Keyring
from stormweaver.keyrings.file import FileKeyring
from stormweaver.keyrings.kmip import KmipKeyring
from stormweaver.keyrings.vault import VaultKeyring

Scope = Literal["global", "database"]


def _q(v: str | int) -> str:
    if isinstance(v, int):
        return str(v)
    return "'" + v.replace("'", "''") + "'"


def add_provider_sql(keyring: Keyring, scope: Scope, name: str) -> str:
    """SELECT statement registering keyring as a pg_tde key provider."""
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
    fn = f"pg_tde_add_{scope}_key_provider_{suffix}"
    return f"SELECT {fn}({', '.join(_q(a) for a in args)})"
