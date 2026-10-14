import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from stormweaver.keyrings.vault import VaultKeyring

KV_ONLY_POLICY = """
path "{mount}/data/*" {{ capabilities = ["create", "read"] }}
path "{mount}/metadata/*" {{ capabilities = ["read", "list"] }}
"""


def with_namespace(kr: VaultKeyring, namespace: str, token_file: Path | None = None) -> VaultKeyring:
    """kr's server and mount, seen from namespace (and token_file if given)"""
    return VaultKeyring(
        url=kr.url,
        mount_path=kr.mount_path,
        token_file=token_file or kr.token_file,
        ca_cert=kr.ca_cert,
        namespace=namespace,
    )


def bao_request(kr: VaultKeyring, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    """OpenBao HTTP API call with kr's token and namespace; returns (status, body), also for error statuses"""
    headers = {"X-Vault-Token": kr.token_file.read_text().strip(), "Content-Type": "application/json"}
    if kr.namespace:
        headers["X-Vault-Namespace"] = kr.namespace
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{kr.url}/v1/{path}", data=data, headers=headers, method=method)
    ctx = ssl.create_default_context(cafile=str(kr.ca_cert))
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    if not raw.strip():
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def _bao_ok(kr: VaultKeyring, method: str, path: str, body: dict | None = None) -> Any:
    status, out = bao_request(kr, method, path, body)
    if status >= 300:
        raise RuntimeError(f"openbao {method} {path}: HTTP {status}: {out}")
    return out


def create_namespace(kr: VaultKeyring, namespace: str) -> None:
    """namespace with a kv-v2 mount at the keyring's mount path"""
    _bao_ok(kr, "POST", f"sys/namespaces/{namespace}", {})
    _bao_ok(
        with_namespace(kr, namespace),
        "POST",
        f"sys/mounts/{kr.mount_path}",
        {"type": "kv", "options": {"version": "2"}},
    )


def prepare_openbao_for_vault_v2(kr: VaultKeyring) -> None:
    # kv-v1 mount and a namespace with kv-v2, as t/vault_v2.pl's bao_setup did
    _bao_ok(kr, "POST", "sys/mounts/kv-v1", {"type": "kv", "options": {"version": "1"}})
    create_namespace(kr, "pgns")


def kv_only_keyring(kr: VaultKeyring, token_file: Path) -> VaultKeyring:
    """kr with a token that can use the kv mount but cannot read mount info"""
    _bao_ok(kr, "PUT", "sys/policies/acl/kv-only", {"policy": KV_ONLY_POLICY.format(mount=kr.mount_path)})
    out = _bao_ok(kr, "POST", "auth/token/create", {"policies": ["kv-only"], "no_default_policy": True})
    token_file.write_text(out["auth"]["client_token"])
    return with_namespace(kr, kr.namespace, token_file)


def read_secret(kr: VaultKeyring, name: str) -> dict | None:
    status, out = bao_request(kr, "GET", f"{kr.mount_path}/data/{name}")
    if status == 404:
        return None
    if status >= 300:
        raise RuntimeError(f"openbao read {name}: HTTP {status}: {out}")
    return out["data"]["data"]


def write_secret(kr: VaultKeyring, name: str, data: dict) -> None:
    _bao_ok(kr, "POST", f"{kr.mount_path}/data/{name}", {"data": data})


def delete_secret(kr: VaultKeyring, name: str) -> None:
    _bao_ok(kr, "DELETE", f"{kr.mount_path}/metadata/{name}")
