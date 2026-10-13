import json
import ssl
import urllib.request

from stormweaver.keyrings.vault import VaultKeyring


def _bao_post(kr: VaultKeyring, path: str, body: dict, namespace: str = "") -> None:
    headers = {"X-Vault-Token": kr.token_file.read_text().strip(), "Content-Type": "application/json"}
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    req = urllib.request.Request(f"{kr.url}/v1/{path}", data=json.dumps(body).encode(), headers=headers)
    ctx = ssl.create_default_context(cafile=str(kr.ca_cert))
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"openbao {path}: HTTP {resp.status}")


def prepare_openbao_for_vault_v2(kr: VaultKeyring) -> None:
    # kv-v1 mount and a namespace with kv-v2, as t/vault_v2.pl's bao_setup did
    _bao_post(kr, "sys/mounts/kv-v1", {"type": "kv", "options": {"version": "1"}})
    _bao_post(kr, "sys/namespaces/pgns", {})
    _bao_post(kr, "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}}, namespace="pgns")
