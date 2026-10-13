from pathlib import Path

import pytest
from stormweaver.keyrings.file import FileKeyring
from stormweaver.keyrings.kmip import KmipKeyring
from stormweaver.keyrings.vault import VaultKeyring

from pgtde.providers import add_provider_sql


def test_file_provider_sql():
    k = FileKeyring("/tmp/kr.per")
    assert add_provider_sql(k, "global", "prov") == "SELECT pg_tde_add_global_key_provider_file('prov', '/tmp/kr.per')"
    assert add_provider_sql(k, "database", "p2") == "SELECT pg_tde_add_database_key_provider_file('p2', '/tmp/kr.per')"


def test_vault_provider_sql():
    k = VaultKeyring(
        url="https://127.0.0.1:8200", mount_path="secret", token_file=Path("/w/token"), ca_cert=Path("/w/ca.pem")
    )
    assert add_provider_sql(k, "database", "v") == (
        "SELECT pg_tde_add_database_key_provider_vault_v2"
        "('v', 'https://127.0.0.1:8200', 'secret', '/w/token', '/w/ca.pem')"
    )


def test_vault_provider_sql_namespace():
    k = VaultKeyring(url="https://h:1", mount_path="m", token_file=Path("/t"), ca_cert=Path("/ca"), namespace="pgns")
    assert add_provider_sql(k, "global", "v").endswith("'/ca', 'pgns')")


def test_kmip_provider_sql():
    k = KmipKeyring(
        host="127.0.0.1",
        port=5696,
        client_cert=Path("/d/client.pem"),
        client_key=Path("/d/client.key"),
        ca_cert=Path("/d/ca.pem"),
    )
    assert add_provider_sql(k, "database", "km") == (
        "SELECT pg_tde_add_database_key_provider_kmip"
        "('km', '127.0.0.1', 5696, '/d/client.pem', '/d/client.key', '/d/ca.pem')"
    )


def test_quote_escaping():
    k = FileKeyring("/tmp/o'brien.per")
    assert "'/tmp/o''brien.per'" in add_provider_sql(k, "global", "p")


def test_bad_scope_and_type():
    from stormweaver.keyrings.base import Keyring

    with pytest.raises(ValueError, match="unknown scope"):
        add_provider_sql(FileKeyring("/x"), "cluster", "p")  # type: ignore[arg-type]

    class Weird(Keyring):  # subclass the adapter doesn't know
        kind = "weird"
        has_service = False

    with pytest.raises(TypeError, match="unsupported keyring"):
        add_provider_sql(Weird(), "global", "p")
