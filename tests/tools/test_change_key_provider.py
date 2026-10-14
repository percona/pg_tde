import json
import re
import shutil

import pytest
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
        _change_ok(change(*args))

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

    node.start()
    st.command_fails(
        change(GLOBAL_OID, "global-provider", "file", "/tmp/file"),
        stderr_re=r"pg_tde_change_key_provider: error: cluster must be shut down",
        msg="gives error on if cluster is running",
    )
    node.stop()


def _encrypted_db(node, file_keyring):
    node.setup_db_key(file_keyring)
    node.safe_sql("CREATE TABLE t (id int, payload text) USING tde_heap")
    node.safe_sql("INSERT INTO t SELECT i, md5(i::text) FROM generate_series(1, 200) i")
    node.safe_sql("CHECKPOINT")
    db_oid = node.sql_value("SELECT oid FROM pg_catalog.pg_database WHERE datname = 'postgres'")
    assert db_oid is not None
    return db_oid


def _providers(node, scope="database"):
    return [[name, ptype, json.loads(opts)] for _, name, ptype, opts in api.list_providers(node, scope=scope)]


def _assert_data_readable(node):
    assert node.sql_value("SELECT count(*) FROM t") == "200"
    assert node.is_encrypted("t")


def _change_ok(cp):
    st.command_ok(cp)
    assert re.search(OK, cp.stdout), cp.stdout


def _offline_move(node, file_keyring, tmp_path, db_oid, *, pgdata_env=False):
    node.stop()
    new = tmp_path / "moved.keys"
    shutil.move(file_keyring.path, new)
    if pgdata_env:
        cp = node.tool(
            "pg_tde_change_key_provider", db_oid, "db-provider", "file", new, env={"PGDATA": str(node.datadir)}
        )
    else:
        cp = node.tool("pg_tde_change_key_provider", "-D", node.datadir, db_oid, "db-provider", "file", new)
    _change_ok(cp)
    return new


def test_change_key_provider_after_key_file_move(tde_node, file_keyring, tmp_path):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    new = _offline_move(node, file_keyring, tmp_path, db_oid)

    node.start()
    _assert_data_readable(node)
    assert _providers(node) == [["db-provider", "file", {"path": str(new)}]]
    node.safe_sql("CREATE TABLE t2 (x text) USING tde_heap")
    node.safe_sql("INSERT INTO t2 VALUES ('after-move')")
    node.restart()
    assert node.safe_sql("SELECT x FROM t2") == [["after-move"]]
    assert node.is_encrypted("t2")
    assert not file_keyring.path.exists()


@pytest.mark.bug("PG-1452")
def test_change_key_provider_datadir_from_pgdata_env(tde_node, file_keyring, tmp_path):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    new = _offline_move(node, file_keyring, tmp_path, db_oid, pgdata_env=True)

    node.start()
    _assert_data_readable(node)
    assert _providers(node) == [["db-provider", "file", {"path": str(new)}]]


def test_change_key_provider_survives_restarts(tde_node, file_keyring, tmp_path):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    new = _offline_move(node, file_keyring, tmp_path, db_oid)

    for _ in range(3):
        node.start()
        _assert_data_readable(node)
        assert _providers(node) == [["db-provider", "file", {"path": str(new)}]]
        node.stop()


def test_change_key_provider_keeps_other_providers(tde_node, file_keyring, tmp_path):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    bystander = tmp_path / "bystander.keys"
    global_keys = tmp_path / "global.keys"
    api.add_provider(node, bystander, "bystander-provider")
    api.add_provider(node, global_keys, "global-provider", scope="global")
    raw_before = api.list_providers(node)
    raw_global_before = api.list_providers(node, scope="global")
    new = _offline_move(node, file_keyring, tmp_path, db_oid)

    node.start()
    _assert_data_readable(node)
    assert _providers(node)[0] == ["db-provider", "file", {"path": str(new)}]
    raw_after = api.list_providers(node)
    assert [r[0] for r in raw_after] == [r[0] for r in raw_before]
    assert raw_after[1] == raw_before[1], "bystander record rewritten"
    assert api.list_providers(node, scope="global") == raw_global_before


@pytest.mark.bug("PG-2863")
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="PG-2863: dbOid parsed with atoi, non-numeric accepted")
@pytest.mark.parametrize(
    "bad_oid", ["not_a_number", "{oid}abc", "-1"], ids=["not-a-number", "oid-with-suffix", "negative-after-dashdash"]
)
def test_change_key_provider_rejects_non_numeric_dboid(tde_node, file_keyring, tmp_path, bad_oid):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    node.stop()
    value = bad_oid.replace("{oid}", db_oid)
    v = re.escape(value)

    cp = node.tool(
        "pg_tde_change_key_provider", "-D", node.datadir, "--", value, "db-provider", "file", tmp_path / "x.keys"
    )
    st.command_fails(cp, stderr_re=rf"(?i)invalid.*{v}|{v}.*invalid")

    node.start()
    _assert_data_readable(node)
    assert _providers(node) == [["db-provider", "file", {"path": str(file_keyring.path)}]]


def _bad(args, stderr_re, *, id, env=None):
    return pytest.param(args, stderr_re, env, id=id)


@pytest.mark.parametrize(
    ("args", "stderr_re", "env"),
    [
        _bad(("{oid}", "db-provider", "file", "{tmp}/x.keys"), r"error: no data directory specified", id="no-datadir"),
        _bad(
            ("{oid}", "db-provider", "file", "{tmp}/x.keys"),
            r'error: could not open file "/global/pg_control" for reading: No such file or directory',
            id="empty-pgdata",
            env={"PGDATA": ""},
        ),
        _bad(
            ("-D", "{tmp}/missing", "{oid}", "db-provider", "file", "{tmp}/x.keys"),
            r'error: could not open file "{tmp}/missing/global/pg_control" for reading: No such file or directory',
            id="missing-datadir",
        ),
        _bad(
            ("-D", "{tmp}/empty", "{oid}", "db-provider", "file", "{tmp}/x.keys"),
            r'error: could not open file "{tmp}/empty/global/pg_control" for reading: No such file or directory',
            id="not-a-datadir",
        ),
        _bad(
            ("-D", "{datadir}", "12345678", "db-provider", "file", "{tmp}/x.keys"),
            r'error: could not open tde file "[^"]+": No such file or directory',
            id="unknown-oid",
        ),
        _bad(
            ("-D", "{datadir}", "-1", "db-provider", "file", "{tmp}/x.keys"),
            r"invalid option -- '1'",
            id="negative-oid-parsed-as-option",
        ),
        _bad(
            ("-D", "{datadir}", "{oid}", "no-such-provider", "file", "{tmp}/x.keys"),
            r'error: provder "no-such-provider" not found for database {oid}',
            id="unknown-provider",
        ),
        _bad(
            ("-D", "{datadir}", GLOBAL_OID, "no-such-provider", "file", "{tmp}/x.keys"),
            rf'error: provder "no-such-provider" not found for database {GLOBAL_OID}',
            id="unknown-global-provider",
        ),
        _bad(("-D", "{datadir}", "{oid}", "db-provider"), r"error: too few arguments", id="too-few"),
        _bad(
            ("-D", "{datadir}", "{oid}", "db-provider", "not_a_real_type", "{tmp}/x.keys"),
            r'error: unknown provider type "not_a_real_type"',
            id="unknown-type",
        ),
        _bad(
            ("-D", "{datadir}", "{oid}", "db-provider", "vault", "http://vault.example:8200", "secret", "/dev/null"),
            r'error: unknown provider type "vault"',
            id="legacy-vault-type",
        ),
        _bad(
            ("-D", "{datadir}", "{oid}", "db-provider", "file"),
            r'error: wrong number of arguments for "file"',
            id="file-no-path",
        ),
        _bad(
            ("-D", "{datadir}", "{oid}", "db-provider", "vault-v2", "http://vault.example:8200", "secret"),
            r'error: wrong number of arguments for "vault-v2"',
            id="vault-v2-no-token",
        ),
        _bad(
            ("-D", "{datadir}", "{oid}", "db-provider", "kmip", "kmip.example", "5696", "/tmp/client.pem"),
            r'error: wrong number of arguments for "kmip"',
            id="kmip-no-key",
        ),
    ],
)
def test_change_key_provider_rejects_bad_arguments(tde_node, file_keyring, tmp_path, monkeypatch, args, stderr_re, env):
    node = tde_node
    db_oid = _encrypted_db(node, file_keyring)
    api.add_provider(node, tmp_path / "global.keys", "global-provider", scope="global")
    node.stop()
    (tmp_path / "empty").mkdir()
    monkeypatch.delenv("PGDATA", raising=False)

    subst = {"{datadir}": str(node.datadir), "{oid}": db_oid, "{tmp}": str(tmp_path)}

    def fill(s, quote=lambda v: v):
        for k, v in subst.items():
            s = s.replace(k, quote(v))
        return s

    st.command_fails(
        node.tool("pg_tde_change_key_provider", *(fill(a) for a in args), env=env),
        stderr_re=fill(stderr_re, re.escape),
    )

    node.start()
    _assert_data_readable(node)
    assert _providers(node) == [["db-provider", "file", {"path": str(file_keyring.path)}]]
    assert _providers(node, scope="global") == [["global-provider", "file", {"path": str(tmp_path / "global.keys")}]]
