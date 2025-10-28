-- complain if script is sourced in psql, rather than via CREATE EXTENSION
\echo Use "ALTER EXTENSION pg_tde UPDATE TO '2.1'" to load this file. \quit

CREATE FUNCTION pg_tde_add_database_key_provider_vault_v2(provider_name TEXT,
                                                vault_url TEXT,
                                                vault_mount_path TEXT,
                                                vault_token_path TEXT,
                                                vault_ca_path TEXT,
                                                vault_namespace TEXT)
RETURNS VOID
LANGUAGE SQL
BEGIN ATOMIC
    SELECT pg_tde_add_database_key_provider('vault-v2', provider_name,
                            json_object('url' VALUE vault_url,
                            'mountPath' VALUE vault_mount_path,
                            'tokenPath' VALUE vault_token_path,
                            'caPath' VALUE vault_ca_path,
                            'namespace' VALUE vault_namespace));
END;

CREATE FUNCTION pg_tde_add_global_key_provider_vault_v2(provider_name TEXT,
                                                        vault_url TEXT,
                                                        vault_mount_path TEXT,
                                                        vault_token_path TEXT,
                                                        vault_ca_path TEXT,
                                                        vault_namespace TEXT)
RETURNS VOID
LANGUAGE SQL
BEGIN ATOMIC
    SELECT pg_tde_add_global_key_provider('vault-v2', provider_name,
                            json_object('url' VALUE vault_url,
                            'mountPath' VALUE vault_mount_path,
                            'tokenPath' VALUE vault_token_path,
                            'caPath' VALUE vault_ca_path,
                            'namespace' VALUE vault_namespace));
END;

CREATE FUNCTION pg_tde_change_database_key_provider_vault_v2(provider_name TEXT,
                                                    vault_url TEXT,
                                                    vault_mount_path TEXT,
                                                    vault_token_path TEXT,
                                                    vault_ca_path TEXT,
                                                    vault_namespace TEXT)
RETURNS VOID
LANGUAGE SQL
BEGIN ATOMIC
    SELECT pg_tde_change_database_key_provider('vault-v2', provider_name,
                            json_object('url' VALUE vault_url,
                            'mountPath' VALUE vault_mount_path,
                            'tokenPath' VALUE vault_token_path,
                            'caPath' VALUE vault_ca_path,
                            'namespace' VALUE vault_namespace));
END;

CREATE FUNCTION pg_tde_change_global_key_provider_vault_v2(provider_name TEXT,
                                                           vault_url TEXT,
                                                           vault_mount_path TEXT,
                                                           vault_token_path TEXT,
                                                           vault_ca_path TEXT,
                                                           vault_namespace TEXT)
RETURNS VOID
LANGUAGE SQL
BEGIN ATOMIC
    SELECT pg_tde_change_global_key_provider('vault-v2', provider_name,
                            json_object('url' VALUE vault_url,
                            'mountPath' VALUE vault_mount_path,
                            'tokenPath' VALUE vault_token_path,
                            'caPath' VALUE vault_ca_path,
                            'namespace' VALUE vault_namespace));
END;
