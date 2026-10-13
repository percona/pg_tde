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


@pytest.fixture
def node(tde_node, file_keyring):
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
    for opts in NON_OBJECT_JSON:
        node.expect_error(NOT_OBJECT, f"SELECT pg_tde_add_database_key_provider('file', 'provider', {opts})")
    for opts, msg in NON_SCALAR:
        node.expect_error(msg, f"SELECT pg_tde_add_database_key_provider('file', 'provider', {opts})")


def test_unwritable_keyring_path(tde_node):
    api.create_extension(tde_node)
    tde_node.expect_error(
        r"Failed to open keyring file /cant-create-file-in-root\.per: (Permission denied|Read-only file system)",
        "SELECT pg_tde_add_database_key_provider_file('will-not-work', '/cant-create-file-in-root.per')",
    )


def test_provider_lifecycle(tde_node, tmp_path):
    node = tde_node
    api.create_extension(node)
    kr1 = FileKeyring(tmp_path / "keyring.per")
    kr2 = FileKeyring(tmp_path / "keyring2.per")
    api.add_provider(node, kr1, "file-provider")
    api.add_provider(node, kr2, "file-provider2")
    node.expect_error(
        r'Key provider "file-provider" already exists\.',
        f"SELECT pg_tde_add_database_key_provider_file('file-provider', '{tmp_path / 'dup.per'}')",
    )

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

    in_use = r"cannot delete provider which is currently in use"
    node.expect_error(in_use, "SELECT pg_tde_delete_database_key_provider('file-provider')")
    api.delete_provider(node, "file-provider2")
    assert [r[1] for r in api.list_providers(node)] == ["file-provider"]

    api.set_key(node, "test-db-key", "file-keyring", scope="global")
    node.expect_error(in_use, "SELECT pg_tde_delete_global_key_provider('file-keyring')")
    api.delete_provider(node, "file-keyring2", scope="global")
    assert [r[1] for r in api.list_providers(node, scope="global")] == ["file-keyring"]


def test_change_provider_validation(node):
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
    node.safe_sql("DROP DATABASE db_using_global_provider")

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


def test_key_name_validation(node):
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
