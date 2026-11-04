import re
import shutil

import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde import api

NOT_OBJECT = r"key provider options must be an object"
VALUE_OBJECT = r"key provider value cannot be an object"
TOO_LARGE = r"too large provider options, maximum size is 1023 bytes"
NON_OBJECT_JSON = ["'\"bare string\"'", "'[\"array\"]'", "'true'", "'null'"]
NON_SCALAR = [
    ("'{\"path\": {}}'", VALUE_OBJECT),
    ('\'{"path": ["array"]}\'', r'unexpected array in field "path"'),
    ("'{\"path\": true}'", r'unexpected boolean in field "path"'),
]
SCOPES = ["database", "global"]
MISSING_PATH = r"file path is missing in the keyring options"
IN_USE = r"cannot delete provider which is currently in use"


@pytest.fixture
def providers_node(tde_node, file_keyring):
    """db provider file-provider and global provider file-keyring share one file"""
    api.create_extension(tde_node)
    api.add_provider(tde_node, file_keyring, "file-provider")
    api.add_provider(tde_node, file_keyring, "file-keyring", scope="global")
    return tde_node


def test_add_provider_validation(tde_node):
    node = tde_node
    api.create_extension(node)
    assert api.key_info(node) is None
    node.expect_error(
        VALUE_OBJECT,
        """SELECT pg_tde_add_database_key_provider('file', 'incorrect-file-provider', '{"path": {"foo": "x.per"}}')""",
    )
    for s in SCOPES:
        fn = f"pg_tde_add_{s}_key_provider"
        node.expect_error(r"provider type cannot be null", f"SELECT {fn}(NULL, 'name', '{{}}')")
        node.expect_error(r"provider name cannot be null", f"SELECT {fn}('file', NULL, '{{}}')")
        node.expect_error(r"provider options cannot be null", f"SELECT {fn}('file', 'name', NULL)")
        node.expect_error(r'provider name "" is too short', f"SELECT {fn}('file', '', '{{}}')")
        res = node.expect_error(r'provider name "K{128}" is too long', f"SELECT {fn}('file', repeat('K', 128), '{{}}')")
        assert "Maximum length is 127 bytes." in res.error_message
        node.expect_error(TOO_LARGE, f"SELECT {fn}('file', 'name', json_build_object('key', repeat('K', 1024)))")
        node.expect_error(r"Invalid provider type\.", f"SELECT {fn}('bogus', 'name', '{{}}')")
        node.expect_error(MISSING_PATH, f"SELECT {fn}('file', 'name', '{{}}')")
        node.expect_error(MISSING_PATH, f"SELECT {fn}_file('name', '')")
    for opts in NON_OBJECT_JSON:
        node.expect_error(NOT_OBJECT, f"SELECT pg_tde_add_database_key_provider('file', 'provider', {opts})")
    for opts, msg in NON_SCALAR:
        node.expect_error(msg, f"SELECT pg_tde_add_database_key_provider('file', 'provider', {opts})")
    for s in SCOPES:
        assert api.list_providers(node, scope=s) == [], s


def test_unwritable_keyring_path(tde_node, tmp_path):
    api.create_extension(tde_node)
    tde_node.expect_error(
        r"Failed to open keyring file /cant-create-file-in-root\.per: (Permission denied|Read-only file system)",
        "SELECT pg_tde_add_database_key_provider_file('will-not-work', '/cant-create-file-in-root.per')",
    )
    tde_node.expect_error(
        rf"Failed to open keyring file {re.escape(str(tmp_path))}: Is a directory",
        f"SELECT pg_tde_add_database_key_provider_file('will-not-work', '{tmp_path}')",
    )
    assert api.list_providers(tde_node) == []


def test_provider_lifecycle(tde_node, tmp_path):
    node = tde_node
    api.create_extension(node)
    kr1 = FileKeyring(tmp_path / "keyring.per")
    kr2 = FileKeyring(tmp_path / "keyring2.per")
    api.add_provider(node, kr1, "file-provider")
    api.add_provider(node, kr2, "file-provider2")
    listing = api.list_providers(node)
    node.expect_error(
        r'Key provider "file-provider" already exists\.',
        f"SELECT pg_tde_add_database_key_provider_file('file-provider', '{tmp_path / 'dup.per'}')",
    )
    assert api.list_providers(node) == listing

    api.create_key(node, "test-db-key", "file-provider")
    node.expect_error(r"principal key not configured for current database", "SELECT pg_tde_verify_key()")
    api.set_key(node, "test-db-key", "file-provider")
    api.verify_key(node)

    node.expect_error(
        r'key provider "not-existent-provider" does not exists',
        f"SELECT pg_tde_change_database_key_provider_file('not-existent-provider', '{kr1.path}')",
    )
    node.expect_error(
        VALUE_OBJECT,
        "SELECT pg_tde_change_database_key_provider('file', 'file-provider', '{\"path\": {\"foo\": \"x.per\"}}')",
    )
    assert [r[1] for r in api.list_providers(node)] == ["file-provider", "file-provider2"]

    api.add_provider(node, kr1, "file-keyring", scope="global")
    api.add_provider(node, kr2, "file-keyring2", scope="global")
    node.expect_error(
        r'Key provider "file-keyring" already exists\.',
        f"SELECT pg_tde_add_global_key_provider_file('file-keyring', '{tmp_path / 'dup.per'}')",
    )
    for s in SCOPES:
        node.expect_error(r'key provider "ghost" does not exists', f"SELECT pg_tde_delete_{s}_key_provider('ghost')")
    node.expect_error(
        r'key provider "ghost" does not exists',
        f"SELECT pg_tde_change_global_key_provider_file('ghost', '{kr1.path}')",
    )

    # generic api with json options
    kr3 = tmp_path / "keyring3.per"
    node.safe_sql(f"SELECT pg_tde_add_global_key_provider('file', 'file-keyring3', json_build_object('path', '{kr3}'))")
    api.create_key(node, "generic-key", "file-keyring3", scope="global")
    assert kr3.exists()

    api.change_provider_file(node, "file-keyring2", str(kr3), scope="global")
    assert ["-2", "file-keyring2", "file", f'{{"path" : "{kr3}"}}'] in api.list_providers(node, scope="global")

    node.expect_error(IN_USE, "SELECT pg_tde_delete_database_key_provider('file-provider')")
    api.delete_provider(node, "file-provider2")
    assert [r[1] for r in api.list_providers(node)] == ["file-provider"]

    api.set_key(node, "test-db-key", "file-keyring", scope="global")
    api.delete_provider(node, "file-provider")
    assert api.list_providers(node) == []
    node.expect_error(IN_USE, "SELECT pg_tde_delete_global_key_provider('file-keyring')")
    api.delete_provider(node, "file-keyring3", scope="global")
    assert sorted(r[1] for r in api.list_providers(node, scope="global")) == ["file-keyring", "file-keyring2"]

    # database providers are per database
    node.safe_sql("CREATE DATABASE other")
    with node.connect(db="other") as other:
        api.create_extension(other)
        assert api.list_providers(other) == []
        assert sorted(r[1] for r in api.list_providers(other, scope="global")) == ["file-keyring", "file-keyring2"]
    node.safe_sql("DROP DATABASE other")

    listing = {s: api.list_providers(node, scope=s) for s in SCOPES}
    node.restart()
    assert {s: api.list_providers(node, scope=s) for s in SCOPES} == listing


def test_change_provider_validation(providers_node, file_keyring, tmp_path):
    node = providers_node
    other = tmp_path / "other.per"
    listing = {s: api.list_providers(node, scope=s) for s in SCOPES}
    for s in SCOPES:
        fn = f"pg_tde_change_{s}_key_provider"
        node.expect_error(r"provider type cannot be null", f"SELECT {fn}(NULL, 'file-keyring', '{{}}')")
        node.expect_error(r"provider name cannot be null", f"SELECT {fn}('file', NULL, '{{}}')")
        node.expect_error(r"provider options cannot be null", f"SELECT {fn}('file', 'file-keyring', NULL)")
    for s, name in (("database", "file-provider"), ("global", "file-keyring")):
        node.expect_error(
            TOO_LARGE,
            f"SELECT pg_tde_change_{s}_key_provider('file', '{name}', json_build_object('key', repeat('V', 1024)))",
        )
    fn = "pg_tde_change_database_key_provider"
    for opts in NON_OBJECT_JSON:
        node.expect_error(NOT_OBJECT, f"SELECT {fn}('file', 'file-provider', {opts})")
    for opts, msg in NON_SCALAR:
        node.expect_error(msg, f"SELECT {fn}('file', 'file-provider', {opts})")
    for s, name in (("database", "file-provider"), ("global", "file-keyring")):
        node.expect_error(MISSING_PATH, f"SELECT pg_tde_change_{s}_key_provider_file('{name}', '')")
    node.expect_error(
        r'key provider "" does not exists', f"SELECT pg_tde_change_database_key_provider_file('', '{other}')"
    )
    # no fallthrough to the other scope
    for s, name in (("database", "file-keyring"), ("global", "file-provider")):
        sql = f"SELECT pg_tde_change_{s}_key_provider_file('{name}', '{other}')"
        node.expect_error(rf'key provider "{name}" does not exists', sql)
    assert {s: api.list_providers(node, scope=s) for s in SCOPES} == listing

    # same name in both scopes, a change touches its own scope only
    api.add_provider(node, file_keyring, "file-provider", scope="global")
    api.change_provider_file(node, "file-provider", str(other))
    assert api.list_providers(node) == [["1", "file-provider", "file", f'{{"path" : "{other}"}}']]
    assert ["-2", "file-provider", "file", f'{{"path" : "{file_keyring.path}"}}'] in api.list_providers(
        node, scope="global"
    )


def test_change_provider_must_keep_keys(tde_node, tmp_path):
    node = tde_node
    api.create_extension(node)
    kr1 = FileKeyring(tmp_path / "global-provider-file-1")
    other = tmp_path / "global-provider-file-2"

    api.add_provider(node, kr1, "global-provider", scope="global")
    api.create_key(node, "server-key", "global-provider", scope="global")
    api.set_server_key(node, "server-key", "global-provider")
    node.expect_error(
        r'key "server-key" used as server key not found in modified key provider "global-provider"',
        f"SELECT pg_tde_change_global_key_provider_file('global-provider', '{other}')",
    )

    api.add_provider(node, kr1, "global-provider2", scope="global")
    node.safe_sql("CREATE DATABASE db_using_global_provider")
    with node.connect(db="db_using_global_provider") as conn:
        api.create_extension(conn)
        api.create_key(conn, "database-key", "global-provider2", scope="global")
        api.set_key(conn, "database-key", "global-provider2", scope="global")
    node.expect_error(
        r'key "database-key" used by database "db_using_global_provider" '
        r'not found in modified key provider "global-provider2"',
        f"SELECT pg_tde_change_global_key_provider_file('global-provider2', '{other}')",
    )
    node.expect_error(IN_USE, "SELECT pg_tde_delete_global_key_provider('global-provider2')")
    node.safe_sql("DROP DATABASE db_using_global_provider")
    api.delete_provider(node, "global-provider2", scope="global")

    node.safe_sql("CREATE DATABASE db_using_database_provider")
    with node.connect(db="db_using_database_provider") as conn:
        api.create_extension(conn)
        api.add_provider(conn, tmp_path / "db-provider-file", "db-provider")
        api.create_key(conn, "database-key", "db-provider")
        api.set_key(conn, "database-key", "db-provider")
        conn.expect_error(
            r'key "database-key" used by database "db_using_database_provider" '
            r'not found in modified key provider "db-provider"',
            f"SELECT pg_tde_change_database_key_provider_file('db-provider', '{tmp_path / 'db-provider-file-2'}')",
        )
    node.safe_sql("DROP DATABASE db_using_database_provider")


def test_key_name_validation(providers_node):
    node = providers_node
    for s in SCOPES:
        node.expect_error(r"provider_name cannot be null", f"SELECT pg_tde_delete_{s}_key_provider(NULL)")
    setters = [
        "pg_tde_set_default_key_using_global_key_provider",
        "pg_tde_set_key_using_database_key_provider",
        "pg_tde_set_key_using_global_key_provider",
        "pg_tde_set_server_key_using_global_key_provider",
    ]
    for fn in setters:
        node.expect_error(r"key provider name cannot be null", f"SELECT {fn}('key', NULL)")
    for fn in setters:
        node.expect_error(r"key name cannot be null", f"SELECT {fn}(NULL, 'file-keyring')")

    creators = [
        ("pg_tde_create_key_using_database_key_provider", "file-provider"),
        ("pg_tde_create_key_using_global_key_provider", "file-keyring"),
    ]
    for fn, prov in creators:
        node.expect_error(r'key name "" is too short', f"SELECT {fn}('', '{prov}')")
        res = node.expect_error(r'key name "K{256}" is too long', f"SELECT {fn}(repeat('K', 256), '{prov}')")
        assert "Maximum length is 255 bytes." in res.error_message

    # both providers point at the same file
    api.create_key(node, "existing-key", "file-provider")
    for fn, prov in creators:
        node.expect_error(
            r'cannot create key "existing-key" because it already exists', f"SELECT {fn}('existing-key', '{prov}')"
        )

    hint = "Use pg_tde_create_key_using_global_key_provider() to create it."
    for fn in setters:
        sql = f"SELECT {fn}('not-existing', 'file-keyring')"
        if "database" in fn:
            node.expect_error(r'key provider "file-keyring" does not exists', sql)
        else:
            res = node.expect_error(r'key "not-existing" does not exist', sql)
            assert hint in res.error_message


FILE_PATH_ROWS = [["1", "5"], ["2", "6"]]


def _provider_row(scope, path):
    return [["1" if scope == "database" else "-1", "file-provider", "file", f'{{"path" : "{path}"}}']]


def _check_readable(node):
    api.verify_key(node)
    assert api.is_encrypted(node, "test_enc") is True
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == FILE_PATH_ROWS


def _check_new_table(node):
    assert api.is_encrypted(node, "test_enc_new") is True
    assert node.safe_sql("SELECT x FROM test_enc_new") == [["7"]]


@pytest.mark.parametrize("scope", SCOPES)
def test_change_provider_file_path(tde_node, tmp_path, scope):
    node = tde_node
    db1 = tmp_path / "db1.keys"
    db2 = tmp_path / "db2.keys"
    api.create_extension(node)
    api.add_provider(node, db1, "file-provider", scope=scope)
    api.create_key(node, "test-key", "file-provider", scope=scope)
    api.set_key(node, "test-key", "file-provider", scope=scope)
    assert api.list_providers(node, scope=scope) == _provider_row(scope, db1)

    node.safe_sql("""
        CREATE TABLE test_enc (id serial, k integer, PRIMARY KEY (id)) USING tde_heap;
        INSERT INTO test_enc (k) VALUES (5), (6);
    """)
    _check_readable(node)

    shutil.move(db1, db2)
    api.change_provider_file(node, "file-provider", str(db2), scope=scope)
    assert api.list_providers(node, scope=scope) == _provider_row(scope, db2)
    _check_readable(node)
    node.safe_sql("CREATE TABLE test_enc_new (x int) USING tde_heap")
    node.safe_sql("INSERT INTO test_enc_new VALUES (7)")
    _check_new_table(node)

    node.restart()
    _check_readable(node)
    _check_new_table(node)

    # move file back, restart, then change provider
    shutil.move(db2, db1)
    node.restart()

    not_found = r'key "test-key" not found in key provider "file-provider"'
    node.expect_error(not_found, "SELECT pg_tde_verify_key()")
    assert api.is_encrypted(node, "test_enc") is True
    node.expect_error(not_found, "SELECT * FROM test_enc ORDER BY id")

    api.change_provider_file(node, "file-provider", str(db1), scope=scope)
    assert api.list_providers(node, scope=scope) == _provider_row(scope, db1)
    _check_readable(node)
    _check_new_table(node)

    api.drop_extension(node, cascade=True)


DBS = ["db_local", "db_other", "db_global", "db_default"]


def _rows(db):
    return [["1", f"{db} secret"]]


def test_database_keys_per_database(tde_node, keyring_obj, tmp_path):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, keyring_obj, "global-provider", scope="global")
    api.create_key(node, "default-key", "global-provider", scope="global")
    api.set_default_key(node, "default-key", "global-provider")
    for db in DBS:
        node.safe_sql(f"CREATE DATABASE {db}")

    info = {
        "db_local": ["1", "db-provider", "local-key"],
        "db_other": ["1", "db-provider", "other-key"],
        "db_global": ["-1", "global-provider", "global-key"],
        "db_default": ["-1", "global-provider", "default-key"],
    }
    with node.connect(db="db_local") as c:
        api.create_extension(c)
        api.add_provider(c, keyring_obj, "db-provider")
        api.create_key(c, "local-key", "db-provider")
        api.set_key(c, "local-key", "db-provider")
    with node.connect(db="db_other") as c:
        api.create_extension(c)
        # database providers are not visible from other databases
        assert api.list_providers(c) == []
        missing = r'key provider "db-provider" does not exists'
        c.expect_error(missing, "SELECT pg_tde_create_key_using_database_key_provider('x', 'db-provider')")
        c.expect_error(missing, "SELECT pg_tde_set_key_using_database_key_provider('local-key', 'db-provider')")
        api.add_provider(c, tmp_path / "other.keys", "db-provider")
        api.create_key(c, "other-key", "db-provider")
        api.set_key(c, "other-key", "db-provider")
    with node.connect(db="db_global") as c:
        api.create_extension(c)
        api.create_key(c, "global-key", "global-provider", scope="global")
        api.set_key(c, "global-key", "global-provider", scope="global")
    with node.connect(db="db_default") as c:
        api.create_extension(c)
    for db in DBS:
        with node.connect(db=db) as c:
            c.safe_sql("CREATE TABLE t (id int PRIMARY KEY, v text) USING tde_heap")
            c.safe_sql(f"INSERT INTO t VALUES (1, '{db} secret')")
            assert api.key_info(c) == info[db], db

    listing = api.list_providers(node, scope="global")
    node.expect_error(IN_USE, "SELECT pg_tde_delete_global_key_provider('global-provider')")
    assert api.list_providers(node, scope="global") == listing

    node.restart()
    for db in DBS:
        with node.connect(db=db) as c:
            api.verify_key(c)
            assert api.key_info(c) == info[db], db
            assert api.is_encrypted(c, "t") is True, db
            assert c.safe_sql("SELECT * FROM t") == _rows(db), db

    for db in DBS:
        with node.connect(db=db) as c:
            c.safe_sql("DROP TABLE t")
            if db != "db_default":
                api.delete_key(c)
            if db in ("db_local", "db_other"):
                api.delete_provider(c, "db-provider")
    api.delete_default_key(node)
    api.delete_provider(node, "global-provider", scope="global")

    node.restart()
    for db in DBS:
        with node.connect(db=db) as c:
            assert api.key_info(c) is None, db
            assert api.list_providers(c) == [], db
            assert api.list_providers(c, scope="global") == [], db
    assert api.default_key_info(node) is None


def _check_restored(conn, info):
    assert api.key_info(conn) == info
    for t, enc in (("t_enc", True), ("t_plain", False)):
        assert api.is_encrypted(conn, t) is enc, t
        assert conn.safe_sql(f"SELECT * FROM {t}") == [["101", "bond"]], t


def test_dump_restore_into_database_with_own_key(tde_node, keyring_obj, tmp_path):
    node = tde_node
    dump = tmp_path / "dump.sql"
    node.safe_sql("CREATE DATABASE src")
    node.safe_sql("CREATE DATABASE dst")
    with node.connect(db="src") as c:
        api.create_extension(c)
        api.add_provider(c, keyring_obj, "db-provider")
        api.create_key(c, "src-key", "db-provider")
        api.set_key(c, "src-key", "db-provider")
        c.safe_sql("""
            CREATE TABLE t_enc (a int PRIMARY KEY, b text) USING tde_heap;
            CREATE TABLE t_plain (a int PRIMARY KEY, b text) USING heap;
            INSERT INTO t_enc VALUES (101, 'bond');
            INSERT INTO t_plain VALUES (101, 'bond');
        """)
    with node.connect(db="dst") as c:
        api.create_extension(c)
        api.add_provider(c, tmp_path / "dst.keys", "file-provider")
        api.create_key(c, "dst-key", "file-provider")
        api.set_key(c, "dst-key", "file-provider")

    cp = node.tool("pg_dump", "-d", "src", "-t", "t_enc", "-t", "t_plain", "-f", dump)
    assert cp.returncode == 0, cp.stderr
    cp = node.psql(file=dump, db="dst")
    assert cp.returncode == 0, cp.stderr

    with node.connect(db="dst") as c:
        _check_restored(c, ["1", "file-provider", "dst-key"])
    node.restart()
    with node.connect(db="dst") as c:
        _check_restored(c, ["1", "file-provider", "dst-key"])
        api.add_provider(c, keyring_obj, "db-provider")
        api.create_key(c, "dst-key2", "db-provider")
        api.set_key(c, "dst-key2", "db-provider")
    node.restart()
    with node.connect(db="dst") as c:
        _check_restored(c, ["2", "db-provider", "dst-key2"])
