import json
from typing import Any, Literal, NamedTuple

from stormweaver.keyrings.base import Keyring
from stormweaver.keyrings.file import FileKeyring
from stormweaver.keyrings.kmip import KmipKeyring
from stormweaver.keyrings.vault import VaultKeyring

Scope = Literal["database", "global"]


class KeyInfo(NamedTuple):
    provider_id: int
    provider_name: str
    key_name: str


class Provider(NamedTuple):
    id: int
    name: str
    type: str
    options: dict[str, Any]


def _provider_args(keyring: Keyring) -> tuple[str, list[str | int]]:
    if isinstance(keyring, FileKeyring):
        return "file", [str(keyring.path)]
    if isinstance(keyring, VaultKeyring):
        args: list[str | int] = [keyring.url, keyring.mount_path, str(keyring.token_file), str(keyring.ca_cert)]
        if keyring.namespace:
            args.append(keyring.namespace)
        return "vault_v2", args
    if isinstance(keyring, KmipKeyring):
        certs = [str(keyring.client_cert), str(keyring.client_key), str(keyring.ca_cert)]
        return "kmip", [keyring.host, keyring.port, *certs]
    raise TypeError(f"unsupported keyring: {type(keyring).__name__}")


class Tde:
    """The pg_tde SQL functions, on a node or on one connection."""

    def __init__(self, db) -> None:
        self._db = db

    def create_extension(self) -> None:
        self._db.execute("CREATE EXTENSION IF NOT EXISTS pg_tde")

    def add_provider(self, name: str, keyring: Keyring, *, scope: Scope = "database") -> None:
        kind, args = _provider_args(keyring)
        placeholders = ", ".join(f"${i}" for i in range(1, len(args) + 2))
        self._db.execute(f"SELECT pg_tde_add_{scope}_key_provider_{kind}({placeholders})", (name, *args))

    def delete_provider(self, name: str, *, scope: Scope = "database") -> None:
        self._db.execute(f"SELECT pg_tde_delete_{scope}_key_provider($1)", (name,))

    def providers(self, *, scope: Scope = "database") -> list[Provider]:
        rows = self._db.query(
            f"SELECT id, name, type, options FROM pg_tde_list_all_{scope}_key_providers() ORDER BY id"
        )
        return [Provider(r.id, r.name, r.type, json.loads(r.options)) for r in rows]

    def create_key(self, key: str, provider: str, *, scope: Scope = "database") -> None:
        self._db.execute(f"SELECT pg_tde_create_key_using_{scope}_key_provider($1, $2)", (key, provider))

    def set_key(self, key: str, provider: str, *, scope: Scope = "database") -> None:
        self._db.execute(f"SELECT pg_tde_set_key_using_{scope}_key_provider($1, $2)", (key, provider))

    def key_info(self) -> KeyInfo | None:
        return self._key_info("pg_tde_key_info")

    def server_key_info(self) -> KeyInfo | None:
        return self._key_info("pg_tde_server_key_info")

    def _key_info(self, fn: str) -> KeyInfo | None:
        r = self._db.row(f"SELECT provider_id, provider_name, key_name FROM {fn}()")
        return None if r.key_name is None else KeyInfo(r.provider_id, r.provider_name, r.key_name)

    def verify_key(self) -> None:
        self._db.execute("SELECT pg_tde_verify_key()")

    def encryption_state(self, rel: str) -> bool | None:
        """pg_tde_is_encrypted(): None for a relation without storage."""
        return self._db.scalar("SELECT pg_tde_is_encrypted($1::regclass)", (rel,))

    def is_encrypted(self, rel: str) -> bool:
        encrypted = self.encryption_state(rel)
        assert encrypted is not None, f"relation {rel!r} has no storage"
        return encrypted
