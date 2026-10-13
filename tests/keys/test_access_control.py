from pgtde import api

ROLE = "regress_pg_tde_access_control"

DENIED = [
    ("pg_tde_create_key_using_database_key_provider", "'test-db-key', 'local-file-provider'"),
    ("pg_tde_set_key_using_database_key_provider", "'test-db-key', 'local-file-provider'"),
    ("pg_tde_delete_key", ""),
    ("pg_tde_list_all_database_key_providers", ""),
    ("pg_tde_list_all_global_key_providers", ""),
    ("pg_tde_key_info", ""),
    ("pg_tde_server_key_info", ""),
    ("pg_tde_default_key_info", ""),
    ("pg_tde_verify_key", ""),
    ("pg_tde_verify_server_key", ""),
    ("pg_tde_verify_default_key", ""),
]

GRANTS = [
    "pg_tde_add_database_key_provider(TEXT, TEXT, JSON)",
    "pg_tde_add_global_key_provider(TEXT, TEXT, JSON)",
    "pg_tde_change_database_key_provider(TEXT, TEXT, JSON)",
    "pg_tde_change_global_key_provider(TEXT, TEXT, JSON)",
    "pg_tde_create_key_using_global_key_provider(TEXT, TEXT)",
    "pg_tde_delete_database_key_provider(TEXT)",
    "pg_tde_delete_global_key_provider(TEXT)",
    "pg_tde_set_default_key_using_global_key_provider(TEXT, TEXT)",
    "pg_tde_set_key_using_global_key_provider(TEXT, TEXT)",
    "pg_tde_set_server_key_using_global_key_provider(TEXT, TEXT)",
    "pg_tde_delete_default_key()",
]

MODIFY = "must be superuser to modify key providers"
GLOBAL = "must be superuser to access global key providers"

SUPERUSER_ONLY = [
    (MODIFY, "SELECT pg_tde_add_database_key_provider_file('local-file-provider', '{k}')"),
    (MODIFY, "SELECT pg_tde_change_global_key_provider_file('local-file-provider', '{k}')"),
    (MODIFY, "SELECT pg_tde_delete_database_key_provider('local-file-provider')"),
    (MODIFY, "SELECT pg_tde_add_global_key_provider_file('global-file-provider', '{k}')"),
    (MODIFY, "SELECT pg_tde_change_global_key_provider_file('global-file-provider', '{k}')"),
    (MODIFY, "SELECT pg_tde_delete_global_key_provider('global-file-provider')"),
    (GLOBAL, "SELECT pg_tde_create_key_using_global_key_provider('key1', 'global-file-provider')"),
    (GLOBAL, "SELECT pg_tde_set_key_using_global_key_provider('key1', 'global-file-provider')"),
    (GLOBAL, "SELECT pg_tde_set_default_key_using_global_key_provider('key1', 'global-file-provider')"),
    (GLOBAL, "SELECT pg_tde_set_server_key_using_global_key_provider('key1', 'global-file-provider')"),
    (GLOBAL, "SELECT pg_tde_delete_default_key()"),
]


def test_access_control(tde_node, file_keyring):
    node = tde_node
    api.create_extension(node)
    api.add_provider(node, file_keyring, "local-file-provider")
    node.safe_sql(f"CREATE USER {ROLE}")

    with node.connect() as conn:
        conn.safe_sql(f"SET ROLE {ROLE}")
        for fn, args in DENIED:
            conn.expect_error(rf"permission denied for function {fn}$", f"SELECT {fn}({args})")

    for sig in GRANTS:
        node.safe_sql(f"GRANT EXECUTE ON FUNCTION {sig} TO {ROLE}")

    # superuser check is hard coded, GRANT EXECUTE must not bypass it
    with node.connect() as conn:
        conn.safe_sql(f"SET ROLE {ROLE}")
        for msg, sql in SUPERUSER_ONLY:
            conn.expect_error(msg, sql.format(k=file_keyring.path))

    api.drop_extension(node, cascade=True)
