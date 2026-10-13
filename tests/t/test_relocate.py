from pgtde import api


def test_relocate(tde_node, file_keyring):
    node = tde_node
    node.safe_sql("CREATE SCHEMA other")
    api.create_extension(node, schema="other")
    node.safe_sql(f"SELECT other.pg_tde_add_database_key_provider_file('file-vault', '{file_keyring.path}')")
    node.expect_error(r'extension "pg_tde" does not support SET SCHEMA', "ALTER EXTENSION pg_tde SET SCHEMA public")
    api.drop_extension(node)
    node.safe_sql("DROP SCHEMA other")
