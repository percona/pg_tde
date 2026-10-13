import socket
import threading

import pytest
import stormweaver.testing as st
from stormweaver import keyrings
from stormweaver.keyrings.kmip import KmipKeyring

from pgtde import api
from pgtde.providers import add_provider_sql

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

        node.stop()
