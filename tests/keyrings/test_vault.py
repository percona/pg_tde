import pytest
import stormweaver.testing as st
from stormweaver import keyrings
from stormweaver.keyrings.vault import VaultKeyring

from pgtde import api
from pgtde.services import prepare_openbao_for_vault_v2
from pgtde.sql import sql_literal

pytestmark = pytest.mark.needs_vault


def _vault_sql(op, name, url, mount, token, ca):
    args = ", ".join(sql_literal(a) for a in (name, url, mount, token, ca))
    return f"SELECT pg_tde_{op}_database_key_provider_vault_v2({args})"


def test_vault_v2(tde_node, tmp_path):
    node = tde_node
    with keyrings.open_keyring("vault", tmp_path / "bao") as kr:
        st.require_managed(kr)
        prepare_openbao_for_vault_v2(kr)
        token, ca = str(kr.token_file), str(kr.ca_cert)
        bad_port_url = "https://127.0.0.1:61"
        http_url = kr.url.replace("https://", "http://", 1)

        api.create_extension(node)

        off = node.log_offset()
        node.safe_sql(_vault_sql("add", "vault-incorrect", kr.url, "DUMMY-MOUNT-PATH", token, ca))
        node.wait_for_log(
            r'WARNING:  failed to get mount info for "https://127\.0\.0\.1:\d+" '
            r'at mountpoint "DUMMY-MOUNT-PATH" \(HTTP 400\)',
            offset=off,
            timeout=10,
        )

        node.expect_error(
            r'vault mount at "cubbyhole" has unsupported engine type "cubbyhole"',
            _vault_sql("add", "vault-incorrect", kr.url, "cubbyhole", token, ca),
        )
        node.expect_error(
            r'vault mount at "kv-v1" has unsupported Key/Value engine version "1"',
            _vault_sql("add", "vault-incorrect", kr.url, "kv-v1", token, ca),
        )

        api.add_provider(node, kr, "vault-v2")
        api.create_key(node, "vault-v2-key", "vault-v2")
        api.set_key(node, "vault-v2-key", "vault-v2")
        node.safe_sql("""
            CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
            INSERT INTO test_enc (x) VALUES (1), (2);
        """)
        assert node.safe_sql("SELECT * FROM test_enc") == [["1"], ["2"]]
        api.verify_key(node)

        node.expect_error(
            r'HTTP\(S\) request to keyring provider "will-not-work" failed',
            _vault_sql("add", "will-not-work", bad_port_url, "secret", token, ca),
        )
        node.expect_error(
            r'HTTP\(S\) request to keyring provider "vault-v2" failed',
            _vault_sql("change", "vault-v2", bad_port_url, "secret", token, ca),
        )
        node.expect_error(
            r'HTTP\(S\) request to keyring provider "vault-v2" failed',
            _vault_sql("change", "vault-v2", kr.url, "secret", token, None),
        )

        off = node.log_offset()
        node.expect_error(
            r'Listing secrets of "http://127\.0\.0\.1:\d+" at mountpoint "secret" failed',
            _vault_sql("change", "vault-v2", http_url, "secret", token, None),
        )
        node.wait_for_log(
            r'WARNING:  failed to get mount info for "http://127\.0\.0\.1:\d+" at mountpoint "secret" \(HTTP 400\)',
            offset=off,
            timeout=10,
        )

        ns = VaultKeyring(
            url=kr.url, mount_path="secret", token_file=kr.token_file, ca_cert=kr.ca_cert, namespace="pgns"
        )
        api.add_provider(node, ns, "vault-v2ns")
        api.create_key(node, "vault-v2-key-in-ns", "vault-v2ns")
        api.set_key(node, "vault-v2-key-in-ns", "vault-v2ns")
        node.safe_sql("""
            CREATE TABLE test_enc_ns (x int PRIMARY KEY) USING tde_heap;
            INSERT INTO test_enc_ns (x) VALUES (1), (2);
        """)
        assert node.safe_sql("SELECT * FROM test_enc_ns") == [["1"], ["2"]]
        api.verify_key(node)

        api.add_provider(node, kr, "vault-v2-global", scope="global")
        api.create_key(node, "vault-v2-global-key", "vault-v2-global", scope="global")
        api.set_key(node, "vault-v2-global-key", "vault-v2-global", scope="global")
        api.set_server_key(node, "vault-v2-global-key", "vault-v2-global")
        assert api.key_info(node)[1:] == ["vault-v2-global", "vault-v2-global-key"]
        assert api.server_key_info(node)[1:] == ["vault-v2-global", "vault-v2-global-key"]
        api.verify_key(node)
        api.verify_server_key(node)
        assert node.safe_sql("SELECT * FROM test_enc UNION ALL SELECT * FROM test_enc_ns ORDER BY 1") == [
            ["1"],
            ["1"],
            ["2"],
            ["2"],
        ]

        node.stop()
