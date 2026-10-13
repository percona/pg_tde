import json
import re

import stormweaver.testing as st

from pgtde import api

OK = r"Key provider updated successfully!"
GLOBAL_OID = "1664"


def test_change_key_provider_cli(tde_node, tools, tmp_path):
    cp = tools.run("pg_tde_change_key_provider", "--help")
    st.command_ok(cp)
    assert re.search(r"Usage:", cp.stdout)
    cp = tools.run("pg_tde_change_key_provider", "--version")
    st.command_ok(cp)
    assert re.search(r"pg_tde_change_key_provider \(PostgreSQL\) ", cp.stdout)

    token_file = tmp_path / "vault_token"
    token_file.write_text("DUMMY")

    node = tde_node
    api.create_extension(node)
    api.add_provider(node, tmp_path / "pg_tde_change_key_provider-global", "global-provider", scope="global")
    api.add_provider(node, tmp_path / "pg_tde_change_key_provider-database", "database-provider")
    db_oid = node.sql_value("SELECT oid FROM pg_catalog.pg_database WHERE datname = 'postgres'")
    assert db_oid is not None
    node.stop()

    def change(*args):
        return node.tool("pg_tde_change_key_provider", "-D", node.datadir, *args)

    def change_ok(*args):
        cp = change(*args)
        st.command_ok(cp)
        assert re.search(OK, cp.stdout), cp.stdout

    def provider(name, scope="database"):
        node.start()
        sql = f"FROM pg_tde_list_all_{scope}_key_providers() WHERE name = '{name}'"
        ptype = node.sql_value(f"SELECT type {sql}")
        opts = json.loads(node.sql_value(f"SELECT options {sql}"))
        node.stop()
        return ptype, opts

    db_path2 = f"{tmp_path}/pg_tde_change_key_provider-database-2"
    change_ok(db_oid, "database-provider", "file", db_path2)
    ptype, opts = provider("database-provider")
    assert ptype == "file"
    assert opts["path"] == db_path2

    change_ok(
        db_oid,
        "database-provider",
        "vault-v2",
        "https://vault-server.example:8200/",
        "mount-path",
        token_file,
        "/tmp/ca_path",
    )
    ptype, opts = provider("database-provider")
    assert ptype == "vault-v2"
    assert opts["url"] == "https://vault-server.example:8200/"
    assert opts["mountPath"] == "mount-path"
    assert opts["tokenPath"] == str(token_file)
    assert opts["caPath"] == "/tmp/ca_path"

    change_ok(db_oid, "database-provider", "vault-v2", "http://vault-server.example:8200/", "mount-path-2", token_file)
    ptype, opts = provider("database-provider")
    assert ptype == "vault-v2"
    assert opts["url"] == "http://vault-server.example:8200/"
    assert opts["mountPath"] == "mount-path-2"
    assert opts["tokenPath"] == str(token_file)
    assert opts["caPath"] == ""

    change_ok(
        db_oid,
        "database-provider",
        "kmip",
        "kmip-server.example",
        "12345",
        "/tmp/cert_path",
        "/tmp/key_path",
        "/tmp/ca_path",
    )
    ptype, opts = provider("database-provider")
    assert ptype == "kmip"
    assert opts["host"] == "kmip-server.example"
    assert opts["port"] == "12345"
    assert opts["certPath"] == "/tmp/cert_path"
    assert opts["keyPath"] == "/tmp/key_path"
    assert opts["caPath"] == "/tmp/ca_path"

    change_ok(
        GLOBAL_OID,
        "global-provider",
        "vault-v2",
        "http://vault-server.example:8200/",
        "mount-path",
        token_file,
        "/tmp/ca_path",
    )
    ptype, opts = provider("global-provider", scope="global")
    assert ptype == "vault-v2"
    assert opts["url"] == "http://vault-server.example:8200/"

    st.command_fails(
        node.tool(
            "pg_tde_change_key_provider",
            "-D",
            "/non/existing/path",
            GLOBAL_OID,
            "global-provider",
            "file",
            "/tmp/file",
        ),
        stderr_re=(
            r'pg_tde_change_key_provider: error: could not open file "/non/existing/path/global/pg_control" '
            r"for reading: No such file or directory"
        ),
        msg="gives error on incorrect data dir",
    )

    node.start()
    st.command_fails(
        change(GLOBAL_OID, "global-provider", "file", "/tmp/file"),
        stderr_re=r"pg_tde_change_key_provider: error: cluster must be shut down",
        msg="gives error on if cluster is running",
    )
    node.stop()

    st.command_fails(
        change("12345678", "global-provider", "file", "/tmp/file"),
        stderr_re=r'error: could not open tde file "[^"]+": No such file or directory',
        msg="gives error on unknown database oid",
    )
    st.command_fails(
        change(GLOBAL_OID, "incorrect-global-provider", "file", "/tmp/file"),
        stderr_re=r'error: provder "incorrect-global-provider" not found for database 1664',
        msg="gives error on unknown key provider",
    )
    st.command_fails(
        change(GLOBAL_OID, "global-provider", "incorrect-provider-type"),
        stderr_re=r'error: unknown provider type "incorrect-provider-type"',
        msg="gives error on unknown provider type",
    )
    for ptype in ("file", "kmip", "vault-v2"):
        st.command_fails(
            change(GLOBAL_OID, "global-provider", ptype),
            stderr_re=rf'error: wrong number of arguments for "{ptype}"',
            msg=f"gives error on missing arguments for {ptype} provider",
        )
