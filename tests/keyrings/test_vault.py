import json
import re
import shutil

import pytest
import stormweaver.testing as st
from stormweaver import keyrings

from pgtde import api
from pgtde.providers import GLOBAL_OID
from pgtde.services import (
    create_namespace,
    delete_secret,
    kv_only_keyring,
    prepare_openbao_for_vault_v2,
    read_secret,
    with_namespace,
    write_secret,
)
from pgtde.sql import sql_literal

pytestmark = pytest.mark.needs_vault


def _vault_sql(op, name, url, mount, token, ca, scope="database"):
    args = ", ".join(sql_literal(a) for a in (name, url, mount, token, ca))
    return f"SELECT pg_tde_{op}_{scope}_key_provider_vault_v2({args})"


def _vault(tmp_path):
    kr = keyrings.open_keyring("vault", tmp_path / "bao")
    st.require_managed(kr)
    return kr


def _token_path(node, name="db-provider"):
    opts = node.sql_value(f"SELECT options FROM pg_tde_list_all_database_key_providers() WHERE name = '{name}'")
    return json.loads(opts)["tokenPath"]


ROWS = [["1", "one"], ["2", "two"]]


def _make_table(conn, t="t"):
    conn.safe_sql(f"CREATE TABLE {t} (id int PRIMARY KEY, v text) USING tde_heap")
    conn.safe_sql(f"INSERT INTO {t} VALUES (1, 'one'), (2, 'two')")


def _check_table(conn, t="t"):
    assert api.is_encrypted(conn, t) is True, t
    assert conn.safe_sql(f"SELECT * FROM {t} ORDER BY id") == ROWS, t


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

        ns = with_namespace(kr, "pgns")
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


def test_add_provider_rejects_empty_options(tde_node, tmp_path):
    node = tde_node
    with _vault(tmp_path) as kr:
        api.create_extension(node)
        url, mount, token, ca = kr.url, kr.mount_path, str(kr.token_file), str(kr.ca_cert)
        missing = str(tmp_path / "no-such-token")
        cases = [
            ("global", ("", "", "", ""), r"missing in the keyring options: tokenPath url mountPath"),
            ("database", ("", "", "", ""), r"missing in the keyring options: tokenPath url mountPath"),
            ("global", (url, mount, "", ""), r"missing in the keyring options: tokenPath"),
            ("global", (url, mount, missing, ""), rf'could not open file "{re.escape(missing)}" for "vault_token"'),
            ("database", ("", mount, token, ca), r"missing in the keyring options: url"),
        ]
        for scope, args, err in cases:
            node.expect_error(err, _vault_sql("add", "vault-empty", *args, scope=scope))
        assert node.sql_value("SELECT 1") == "1"
        for scope in ("database", "global"):
            assert api.list_providers(node, scope=scope) == [], scope


@pytest.mark.bug("PG-1959")
def test_namespace_providers_survive_restart(tde_node, tmp_path):
    node = tde_node
    with _vault(tmp_path) as kr:
        create_namespace(kr, "pgns")
        ns = with_namespace(kr, "pgns")
        api.create_extension(node)
        api.add_provider(node, ns, "ns-global", scope="global")
        api.create_key(node, "ns-global-key", "ns-global", scope="global")
        api.set_key(node, "ns-global-key", "ns-global", scope="global")
        api.set_server_key(node, "ns-global-key", "ns-global")
        _make_table(node)
        node.safe_sql("CREATE DATABASE db1")
        with node.connect(db="db1") as c:
            api.create_extension(c)
            api.add_provider(c, ns, "ns-db")
            api.create_key(c, "ns-db-key", "ns-db")
            api.set_key(c, "ns-db-key", "ns-db")
            _make_table(c)

        for key in ("ns-global-key", "ns-db-key"):
            assert read_secret(ns, key) is not None, key
            assert read_secret(kr, key) is None, key

        node.restart()
        api.verify_key(node)
        api.verify_server_key(node)
        assert api.key_info(node) == ["-1", "ns-global", "ns-global-key"]
        assert api.server_key_info(node) == ["-1", "ns-global", "ns-global-key"]
        _check_table(node)
        with node.connect(db="db1") as c:
            api.verify_key(c)
            assert api.key_info(c) == ["1", "ns-db", "ns-db-key"]
            _check_table(c)
        node.stop()


@pytest.mark.parametrize("namespace", ["", "pgns"], ids=["root", "namespace"])
def test_kv_only_token_without_mount_read(tde_node, tmp_path, namespace):
    node = tde_node
    with _vault(tmp_path) as kr:
        if namespace:
            create_namespace(kr, namespace)
        admin = with_namespace(kr, namespace)
        kv = kv_only_keyring(admin, tmp_path / "kv-only-token")
        api.create_extension(node)

        off = node.log_offset()
        api.add_provider(node, kv, "kv-db")
        warning = (
            rf'WARNING:  failed to get mount info for ".*" at mountpoint "{re.escape(kr.mount_path)}" \(HTTP 403\)'
        )
        node.wait_for_log(warning, offset=off)
        api.add_provider(node, kv, "kv-global", scope="global")
        api.create_key(node, "kv-db-key", "kv-db")
        api.set_key(node, "kv-db-key", "kv-db")
        api.create_key(node, "kv-server-key", "kv-global", scope="global")
        api.set_server_key(node, "kv-server-key", "kv-global")
        _make_table(node)
        assert read_secret(admin, "kv-db-key") is not None

        node.restart()
        api.verify_key(node)
        api.verify_server_key(node)
        _check_table(node)
        node.stop()


def test_read_fails_until_secret_restored(tde_node, tmp_path):
    node = tde_node
    with _vault(tmp_path) as kr:
        node.setup_db_key(kr)
        _make_table(node)
        node.safe_sql("CHECKPOINT")
        secret = read_secret(kr, "test-db-key")
        assert secret is not None
        delete_secret(kr, "test-db-key")
        assert read_secret(kr, "test-db-key") is None

        node.restart()
        not_found = r'key "test-db-key" not found in key provider "db-provider"'
        node.expect_error(not_found, "SELECT pg_tde_verify_key()")
        node.expect_error(not_found, "SELECT * FROM t")

        token2 = tmp_path / "token2"
        shutil.copy(kr.token_file, token2)
        node.expect_error(
            r'key "test-db-key" used by database "postgres" not found in modified key provider "db-provider"',
            _vault_sql("change", "db-provider", kr.url, kr.mount_path, str(token2), str(kr.ca_cert)),
        )
        assert _token_path(node) == str(kr.token_file)

        write_secret(kr, "test-db-key", secret)
        node.safe_sql(_vault_sql("change", "db-provider", kr.url, kr.mount_path, str(token2), str(kr.ca_cert)))
        assert _token_path(node) == str(token2)
        api.verify_key(node)
        _check_table(node)

        node.restart()
        api.verify_key(node)
        _check_table(node)
        node.stop()


@pytest.mark.parametrize("via", ["sql", "cli"])
def test_change_provider_while_in_use(tde_node, tmp_path, via):
    node = tde_node
    with _vault(tmp_path) as kr:
        node.setup_db_key(kr)
        _make_table(node)
        node.safe_sql("CHECKPOINT")

        token2 = tmp_path / "token2"
        shutil.copy(kr.token_file, token2)
        moved = with_namespace(kr, "", token2)
        if via == "sql":
            api.change_provider(node, moved, "db-provider")
        else:
            db_oid = node.sql_value("SELECT oid FROM pg_database WHERE datname = 'postgres'")
            assert db_oid is not None
            node.stop()
            cp = node.tool(
                "pg_tde_change_key_provider",
                "-D",
                node.datadir,
                db_oid,
                "db-provider",
                "vault-v2",
                kr.url,
                kr.mount_path,
                token2,
                kr.ca_cert,
            )
            st.command_ok(cp)
            node.start()
        assert _token_path(node) == str(token2)
        kr.token_file.unlink()

        api.verify_key(node)
        _check_table(node)
        _make_table(node, "t_new")
        node.restart()
        api.verify_key(node)
        assert api.key_info(node) == ["1", "db-provider", "test-db-key"]
        _check_table(node)
        _check_table(node, "t_new")
        node.stop()


def _use_key(conn, kr, provider, key, *, scope="database"):
    if scope == "database":
        api.add_provider(conn, kr, provider)
    api.create_key(conn, key, provider, scope=scope)
    api.set_key(conn, key, provider, scope=scope)


@pytest.mark.needs_kmip
def test_vault_and_kmip_providers_in_one_cluster(tde_node, tmp_path):
    node = tde_node
    with _vault(tmp_path) as vault, keyrings.open_keyring("kmip", tmp_path / "kmip") as kmip:
        st.require_managed(kmip)
        api.create_extension(node)
        api.add_provider(node, vault, "vault-global", scope="global")
        api.add_provider(node, kmip, "kmip-global", scope="global")
        api.create_key(node, "vault-default", "vault-global", scope="global")
        api.set_default_key(node, "vault-default", "vault-global")

        info = {
            "db_vault": ["1", "vault-db", "vault-key"],
            "db_kmip": ["-2", "kmip-global", "kmip-db-key"],
            "db_default": ["-2", "kmip-global", "kmip-default"],
            "db_rot": ["3", "file-db", "file-key"],
        }
        for db in info:
            node.safe_sql(f"CREATE DATABASE {db}")
        with node.connect(db="db_vault") as c:
            api.create_extension(c)
            _use_key(c, vault, "vault-db", "vault-key")
            _make_table(c)
        with node.connect(db="db_kmip") as c:
            api.create_extension(c)
            _use_key(c, kmip, "kmip-global", "kmip-db-key", scope="global")
            _make_table(c)
        with node.connect(db="db_default") as c:
            api.create_extension(c)
            _make_table(c)
            assert api.key_info(c) == ["-1", "vault-global", "vault-default"]

        api.create_key(node, "kmip-default", "kmip-global", scope="global")
        api.set_default_key(node, "kmip-default", "kmip-global")
        assert api.default_key_info(node) == ["-2", "kmip-global", "kmip-default"]

        tables = []
        with node.connect(db="db_rot") as c:
            api.create_extension(c)
            steps = [
                (kmip, "kmip-global", "kmip-rot-key", "global", ["-2", "kmip-global", "kmip-rot-key"]),
                (vault, "vault-db", "vault-rot-key", "database", ["1", "vault-db", "vault-rot-key"]),
                (kmip, "kmip-db", "kmip-rot-key2", "database", ["2", "kmip-db", "kmip-rot-key2"]),
                (tmp_path / "file-db.keys", "file-db", "file-key", "database", info["db_rot"]),
            ]
            for kr, provider, key, scope, key_info in steps:
                _use_key(c, kr, provider, key, scope=scope)
                assert api.key_info(c) == key_info
                tables.append(f"t_{len(tables)}")
                _make_table(c, tables[-1])
                for t in tables:
                    _check_table(c, t)

        node.restart()
        for db, key_info in info.items():
            with node.connect(db=db) as c:
                api.verify_key(c)
                assert api.key_info(c) == key_info, db
                for t in tables if db == "db_rot" else ["t"]:
                    _check_table(c, t)
        assert api.default_key_info(node) == ["-2", "kmip-global", "kmip-default"]
        node.stop()


def _global_options(node, name="ns-global"):
    opts = node.sql_value(f"SELECT options FROM pg_tde_list_all_global_key_providers() WHERE name = '{name}'")
    return json.loads(opts)


def _setup_error(fn):
    # only the final checks may xfail
    try:
        return fn()
    except AssertionError as e:
        raise RuntimeError(f"setup failed: {e}") from e


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="PG-2875: pg_tde_change_key_provider drops vault namespace"
)
@pytest.mark.bug("PG-2875")
def test_change_key_provider_cli_keeps_namespace(tde_node, tmp_path):
    node = tde_node
    with _vault(tmp_path) as kr:
        ns = with_namespace(kr, "pgns")

        def setup():
            create_namespace(kr, "pgns")
            node.setup_server_key(ns, provider="ns-global", wal_encrypt=True)
            api.create_key(node, "db-key", "ns-global", scope="global")
            api.set_key(node, "db-key", "ns-global", scope="global")
            node.restart()
            _make_table(node)
            assert _global_options(node)["namespace"] == "pgns"
            node.stop()
            cp = node.tool(
                "pg_tde_change_key_provider",
                "-D",
                node.datadir,
                GLOBAL_OID,
                "ns-global",
                "vault-v2",
                kr.url,
                kr.mount_path,
                kr.token_file,
                kr.ca_cert,
            )
            st.command_ok(cp)

        _setup_error(setup)
        off = node.log_offset()
        try:
            node.start()
        except RuntimeError as e:
            log = node.log_since(off)
            if 'key "server-key" not found in key provider "ns-global"' not in log:
                raise
            raise AssertionError(f"server did not start after the change:\n{log}") from e
        assert _global_options(node).get("namespace") == "pgns"
        api.verify_server_key(node)
        _check_table(node)
        node.stop()
