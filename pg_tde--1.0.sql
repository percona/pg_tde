/* contrib/pg_tde/pg_tde--1.0.sql */

-- complain if script is sourced in psql, rather than via CREATE EXTENSION
\echo Use "CREATE EXTENSION pg_tde" to load this file. \quit

-- pg_tde catalog tables
CREATE SCHEMA percona_tde;
CREATE TABLE percona_tde.pg_tde_key_provider(provider_id SERIAL,
        keyring_type VARCHAR(10) CHECK (keyring_type IN ('file', 'kmip', 'vault-v2')),
        provider_name VARCHAR(256) UNIQUE NOT NULL, options JSON, PRIMARY KEY(provider_id)) using heap;

-- Key Provider Management
CREATE OR REPLACE FUNCTION pg_tde_set_master_key(provider_type VARCHAR(10), provider_name VARCHAR(128), options JSON)
RETURNS INT
AS $$
    INSERT INTO percona_tde.pg_tde_key_provider (keyring_type, provider_name, options) VALUES (provider_type, provider_name, options) RETURNING provider_id;
$$
LANGUAGE SQL;


CREATE OR REPLACE FUNCTION pg_tde_add_wallet(provider_type VARCHAR(10), provider_name VARCHAR(128), options JSON)
RETURNS INT
AS $$
    INSERT INTO percona_tde.pg_tde_key_provider (keyring_type, provider_name, options) VALUES (provider_type, provider_name, options) RETURNING provider_id;
$$
LANGUAGE SQL;

CREATE OR REPLACE FUNCTION pg_tde_add_file_wallet(provider_name VARCHAR(128), file_path TEXT)
RETURNS INT
AS $$
    SELECT pg_tde_add_wallet('file', provider_name,
                json_object('type' VALUE 'file', 'path' VALUE file_path));
$$
LANGUAGE SQL;

CREATE OR REPLACE FUNCTION pg_tde_add_vault_v2_wallet(provider_name VARCHAR(128),
                                                        valut_token TEXT,
                                                        valut_url TEXT,
                                                        valut_mount_path TEXT,
                                                        valut_ca_path TEXT)
RETURNS INT
AS $$
    SELECT pg_tde_add_wallet('vault-v2', provider_name,
                            json_object('type' VALUE 'vault-v2',
                            'url' VALUE valut_url,
                            'token' VALUE valut_token,
                            'mountPath' VALUE valut_mount_path,
                            'caPath' VALUE valut_ca_path));
$$
LANGUAGE SQL;

CREATE FUNCTION pg_tde_get_keyprovider(provider_name text)
RETURNS VOID
AS 'MODULE_PATHNAME'
LANGUAGE C;
-- Table access method
CREATE FUNCTION pg_tdeam_handler(internal)
RETURNS table_am_handler
AS 'MODULE_PATHNAME'
LANGUAGE C;

CREATE FUNCTION pgtde_is_encrypted(table_name VARCHAR)
RETURNS boolean
AS $$ SELECT amname = 'pg_tde' FROM pg_class INNER JOIN pg_am ON pg_am.oid = pg_class.relam WHERE relname = table_name $$
LANGUAGE SQL;

CREATE FUNCTION pg_tde_set_master_key(master_key_name text, provider_name text)
RETURNS VOID
AS 'MODULE_PATHNAME'
LANGUAGE C;


-- Access method
CREATE ACCESS METHOD pg_tde TYPE TABLE HANDLER pg_tdeam_handler;
COMMENT ON ACCESS METHOD pg_tde IS 'pg_tde table access method';
