import re

from pgtde import api

PUBLIC_FUNCS_SQL = """
SELECT pg_proc.oid::regprocedure::text
FROM pg_catalog.pg_proc
JOIN pg_catalog.pg_language ON prolang = pg_language.oid
LEFT JOIN LATERAL aclexplode(proacl) ON TRUE
WHERE proname LIKE 'pg_tde%' AND (lanname = 'c' OR prosecdef)
  AND (grantee IS NULL OR grantee = 0)
ORDER BY 1
"""


def control_default_version(pg_install) -> str:
    control = (pg_install.sharedir / "extension" / "pg_tde.control").read_text()
    return re.search(r"default_version\s*=\s*'([^']+)'", control).group(1)


def test_basic(tde_node, file_keyring, pg_install):
    node = tde_node
    api.create_extension(node)

    # only whitelisted functions are callable by public
    assert [r[0] for r in node.safe_sql(PUBLIC_FUNCS_SQL)] == ["pg_tde_is_encrypted(regclass)", "pg_tde_version()"]
    assert node.safe_sql("SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_tde'") == [
        ["pg_tde", control_default_version(pg_install)]
    ]

    node.expect_error(
        r"principal key not configured", "CREATE TABLE test_enc (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap"
    )

    node.setup_db_key(file_keyring)
    node.safe_sql("CREATE TABLE test_enc (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap")
    node.safe_sql("INSERT INTO test_enc (k) VALUES ('foobar'), ('barfoo')")
    expected = [["1", "foobar"], ["2", "barfoo"]]
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == expected

    node.restart()
    assert node.safe_sql("SELECT * FROM test_enc ORDER BY id") == expected
    node.assert_not_on_disk("test_enc", "foo")

    # encrypted table can be dropped without access to the principal key
    node.stop()
    file_keyring.path.unlink()
    node.start()
    node.expect_error(r'key "test-db-key" not found in key provider "db-provider"', "SELECT pg_tde_verify_key()")
    node.safe_sql("DROP TABLE test_enc")
    api.drop_extension(node)


def test_version(tde_node, pg_install, pg_major):
    api.create_extension(tde_node)
    v = api.version(tde_node)
    m = re.fullmatch(r"pg_tde (\d+\.\d+)\.\d+", v)
    assert m, v
    assert m.group(1) == control_default_version(pg_install)
    if pg_major >= 18:
        rows = tde_node.safe_sql(
            "SELECT module_name, version FROM pg_get_loaded_modules() WHERE file_name IN ('pg_tde.so', 'pg_tde.dylib')"
        )
        assert rows == [["pg_tde", v.split()[1]]]


def test_set_schema_rejected(tde_node, file_keyring):
    node = tde_node
    node.safe_sql("CREATE SCHEMA other")
    api.create_extension(node, schema="other")
    node.safe_sql(f"SELECT other.pg_tde_add_database_key_provider_file('file-vault', '{file_keyring.path}')")
    node.expect_error(r'extension "pg_tde" does not support SET SCHEMA', "ALTER EXTENSION pg_tde SET SCHEMA public")
    api.drop_extension(node)
    node.safe_sql("DROP SCHEMA other")
