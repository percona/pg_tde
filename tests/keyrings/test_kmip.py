import json
import shutil
import socket
import threading

import pytest
import stormweaver.testing as st
from stormweaver import keyrings
from stormweaver.keyrings.kmip import KmipKeyring

from pgtde import api
from pgtde.providers import GLOBAL_OID, add_provider_sql, change_provider_sql
from pgtde.wal import wal_contains

pytestmark = pytest.mark.needs_kmip


class _RejectListener:
    """Accept TCP then close at once, so the TLS handshake fails fast."""

    def __enter__(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(5)
        self._srv.settimeout(0.5)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def _run(self):
        while not self._stop:
            try:
                c, _ = self._srv.accept()
                c.close()
            except OSError:
                pass

    def __exit__(self, *exc):
        self._stop = True
        self._srv.close()
        self._t.join(timeout=2)


def _read(node):
    return [r[0] for r in node.safe_sql("SELECT k FROM test_enc ORDER BY id")]


def _kmip(tmp_path):
    kr = keyrings.open_keyring("kmip", tmp_path / "kmip")
    st.require_managed(kr)
    return kr


def _closed_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


KMIP_FETCH_FAILED = ("could not retrieve key from KMIP server", "failed to retrieve principal key")


def test_kmip(tde_node, tmp_path):
    node = tde_node
    with keyrings.open_keyring("kmip", tmp_path / "kmip") as kr:
        st.require_managed(kr)
        api.create_extension(node)
        api.add_provider(node, kr, "kmip-prov")
        api.create_key(node, "kmip-key", "kmip-prov")
        api.set_key(node, "kmip-key", "kmip-prov")
        node.safe_sql("CREATE TABLE test_enc (id SERIAL, k INTEGER NOT NULL, PRIMARY KEY (id)) USING tde_heap")
        node.safe_sql("INSERT INTO test_enc (k) VALUES (1), (2), (3)")
        assert _read(node) == ["1", "2", "3"]

        # cold cache, key re-fetched from KMIP
        node.restart()
        assert _read(node) == ["1", "2", "3"]

        api.create_key(node, "kmip-key2", "kmip-prov")
        api.set_key(node, "kmip-key2", "kmip-prov")
        node.safe_sql("INSERT INTO test_enc (k) VALUES (4), (5)")
        assert _read(node) == ["1", "2", "3", "4", "5"]

        node.restart()
        assert _read(node) == ["1", "2", "3", "4", "5"]

        # same TLS/ports, empty DB
        node.stop()
        kr.restart_service(fresh=True)
        node.start()
        node.expect_error(r"(?i)not found in key provider", "SELECT k FROM test_enc ORDER BY id")

        with _RejectListener() as lst:
            bad = KmipKeyring(
                host="127.0.0.1",
                port=lst.port,
                client_cert=kr.client_cert,
                client_key=kr.client_key,
                ca_cert=kr.ca_cert,
            )
            node.expect_error(
                r"(?i)SSL error|BIO_do_connect|handshake|EOF", add_provider_sql(bad, "database", "will-not-work")
            )

        refused = KmipKeyring(
            host="127.0.0.1",
            port=_closed_port(),
            client_cert=kr.client_cert,
            client_key=kr.client_key,
            ca_cert=kr.ca_cert,
        )
        node.expect_error(r"could not connect to KMIP server", add_provider_sql(refused, "global", "will-not-work"))
        assert [r[1] for r in api.list_providers(node)] == ["kmip-prov"]
        assert api.list_providers(node, scope="global") == []

        node.stop()


def test_add_provider_rejects_empty_paths(tde_node, tmp_path):
    node = tde_node
    with _kmip(tmp_path) as kr:
        api.create_extension(node)
        cert, key = str(kr.client_cert), str(kr.client_key)
        cases = [
            ("global", ("", "", ""), "caPath certPath keyPath"),
            ("database", ("", "", ""), "caPath certPath keyPath"),
            ("global", (cert, key, ""), "caPath"),
            ("global", (cert, "", ""), "caPath keyPath"),
            ("database", (cert, "", ""), "caPath keyPath"),
        ]
        for scope, (c, k, ca), missing in cases:
            args = f"'kmip-empty', '{kr.host}', {kr.port}, '{c}', '{k}', '{ca}'"
            sql = f"SELECT pg_tde_add_{scope}_key_provider_kmip({args})"
            node.expect_error(rf"missing in the keyring options: {missing}$", sql)
        assert node.sql_value("SELECT 1") == "1"
        for scope in ("database", "global"):
            assert api.list_providers(node, scope=scope) == [], scope


def _rotate_global(node, key):
    api.create_key(node, key, "kmip-global", scope="global")
    api.set_key(node, key, "kmip-global", scope="global")
    api.set_server_key(node, key, "kmip-global")
    assert api.key_info(node) == ["-1", "kmip-global", key]
    assert api.server_key_info(node) == ["-1", "kmip-global", key]


def _gen_table(node, gen):
    node.safe_sql(f"CREATE TABLE gen_{gen} (id int PRIMARY KEY, v text) USING tde_heap")
    node.safe_sql(f"INSERT INTO gen_{gen} SELECT i, 'kmip-gen-{gen}-' || i FROM generate_series(1, 1000) i")


def _check_gens(node, gens):
    api.verify_key(node)
    api.verify_server_key(node)
    for gen in range(gens):
        assert api.is_encrypted(node, f"gen_{gen}") is True, gen
        assert node.sql_value(f"SELECT count(*) FROM gen_{gen}") == "1000", gen
        assert node.sql_value(f"SELECT v FROM gen_{gen} WHERE id = 1000") == f"kmip-gen-{gen}-1000", gen


@pytest.mark.bug("PG-2125")
def test_global_key_rotations_survive_restarts(tde_node, tmp_path):
    node = tde_node
    with _kmip(tmp_path) as kr:
        api.create_extension(node)
        api.add_provider(node, kr, "kmip-global", scope="global")
        _rotate_global(node, "key-0")
        node.expect_error(
            r'cannot create key "key-0" because it already exists',
            "SELECT pg_tde_create_key_using_global_key_provider('key-0', 'kmip-global')",
        )
        api.set_wal_encrypt(node, True)
        node.restart()
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        _gen_table(node, 0)

        for gen in range(1, 5):
            _rotate_global(node, f"key-{gen}")
            _gen_table(node, gen)
            node.safe_sql("CHECKPOINT")
            if gen % 2 == 0:
                node.restart()
                assert api.key_info(node) == ["-1", "kmip-global", f"key-{gen}"]
            _check_gens(node, gen + 1)

        node.restart()
        _check_gens(node, 5)
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        assert not wal_contains(node, "kmip-gen-")
        node.stop()


@pytest.mark.bug("PG-2588")
def test_default_key_survives_restarts(tde_node, tmp_path):
    node = tde_node
    default = ["-1", "global-provider", "default-key"]

    def no_fetch_errors(off):
        log = node.log_since(off)
        for marker in KMIP_FETCH_FAILED:
            assert marker not in log, log

    with _kmip(tmp_path) as kr:
        node.setup_default_key(kr)
        node.safe_sql("CREATE TABLE def_t (id int PRIMARY KEY, v text) USING tde_heap")
        node.safe_sql("INSERT INTO def_t SELECT i, md5(i::text) FROM generate_series(1, 100) i")
        for cycle in range(1, 4):
            node.safe_sql(f"INSERT INTO def_t VALUES ({1000 + cycle}, 'cycle-{cycle}')")
            off = node.log_offset()
            node.restart()
            assert api.key_info(node) == default
            assert node.sql_value("SELECT count(*) FROM def_t") == str(100 + cycle)
            assert node.sql_value(f"SELECT v FROM def_t WHERE id = {1000 + cycle}") == f"cycle-{cycle}"
            no_fetch_errors(off)

        node.safe_sql("CREATE DATABASE child")
        with node.connect(db="child") as c:
            api.create_extension(c)
            c.safe_sql("CREATE TABLE t (id int PRIMARY KEY) USING tde_heap")
            c.safe_sql("INSERT INTO t VALUES (1)")
        off = node.log_offset()
        node.restart()
        with node.connect(db="child") as c:
            assert api.key_info(c) == default
            assert api.is_encrypted(c, "t") is True
            assert c.safe_sql("SELECT * FROM t") == [["1"]]
        assert api.is_encrypted(node, "def_t") is True
        no_fetch_errors(off)
        node.stop()


def _copy_certs(kr, dest):
    dest.mkdir()
    paths = []
    for p in (kr.client_cert, kr.client_key, kr.ca_cert):
        shutil.copy(p, dest / p.name)
        paths.append(dest / p.name)
    return KmipKeyring(host=kr.host, port=kr.port, client_cert=paths[0], client_key=paths[1], ca_cert=paths[2])


def _options(node, scope):
    opts = node.sql_value(f"SELECT options FROM pg_tde_list_all_{scope}_key_providers() WHERE name = 'kmip-prov'")
    return json.loads(opts)


def _verify(node, scope):
    api.verify_key(node)
    if scope == "global":
        api.verify_server_key(node)


@pytest.mark.parametrize("via", ["sql", "cli"])
@pytest.mark.parametrize("scope", ["database", "global"])
def test_change_provider_while_in_use(tde_node, tmp_path, scope, via):
    node = tde_node
    with _kmip(tmp_path) as kr:
        moved = _copy_certs(kr, tmp_path / "moved")
        api.create_extension(node)
        api.add_provider(node, kr, "kmip-prov", scope=scope)
        api.create_key(node, "kmip-key", "kmip-prov", scope=scope)
        api.set_key(node, "kmip-key", "kmip-prov", scope=scope)
        if scope == "global":
            api.set_server_key(node, "kmip-key", "kmip-prov")
        node.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
        node.safe_sql("INSERT INTO t SELECT i, md5(i::text) FROM generate_series(1, 50) i")
        node.safe_sql("CHECKPOINT")

        if via == "sql":
            node.expect_error(r'key provider "ghost" does not exists', change_provider_sql(moved, scope, "ghost"))
            api.change_provider(node, moved, "kmip-prov", scope=scope)
        else:
            oid = GLOBAL_OID
            if scope == "database":
                oid = node.sql_value("SELECT oid FROM pg_database WHERE datname = 'postgres'")
            assert oid is not None
            node.stop()
            cp = node.tool(
                "pg_tde_change_key_provider",
                "-D",
                node.datadir,
                oid,
                "kmip-prov",
                "kmip",
                moved.host,
                str(moved.port),
                moved.client_cert,
                moved.client_key,
                moved.ca_cert,
            )
            st.command_ok(cp)
            node.start()
        opts = _options(node, scope)
        assert (opts["certPath"], opts["keyPath"], opts["caPath"]) == (
            str(moved.client_cert),
            str(moved.client_key),
            str(moved.ca_cert),
        )
        for p in (kr.client_cert, kr.client_key):
            p.unlink()

        _verify(node, scope)
        assert node.sql_value("SELECT count(*) FROM t") == "50"
        node.safe_sql("CREATE TABLE t_new (x int) USING tde_heap")
        node.safe_sql("INSERT INTO t_new VALUES (7)")
        node.restart()
        _verify(node, scope)
        assert api.key_info(node)[1:] == ["kmip-prov", "kmip-key"]
        for t in ("t", "t_new"):
            assert api.is_encrypted(node, t) is True, t
        assert node.sql_value("SELECT count(*) FROM t") == "50"
        assert node.safe_sql("SELECT x FROM t_new") == [["7"]]
        node.stop()
