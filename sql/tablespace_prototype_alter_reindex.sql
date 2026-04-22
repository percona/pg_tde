-- Cross-tablespace ALTER INDEX SET TABLESPACE and REINDEX TABLESPACE are allowed.
-- pg_tde_list_mixed_encryption() reports the resulting mismatches.

\! rm -f '/tmp/pg_tde_prototype_alter.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_prototype_alter.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

SET allow_in_place_tablespaces = true;
CREATE TABLESPACE enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('enc_ts');

CREATE TABLE t_enc (x int) TABLESPACE enc_ts;
CREATE INDEX i_enc ON t_enc (x);

CREATE TABLE t_plain (x int);
CREATE INDEX i_plain ON t_plain (x);

-- Cross-side ALTER INDEX SET TABLESPACE succeeds.
ALTER INDEX i_enc SET TABLESPACE pg_default;
ALTER INDEX i_plain SET TABLESPACE enc_ts;

-- Helper reports both cross-side pairs.
SELECT parent, parent_encrypted, child, child_encrypted, relationship
FROM pg_tde_list_mixed_encryption()
WHERE parent::text IN ('t_enc','t_plain')
ORDER BY parent::text, child::text;

-- Reset to same-side.
ALTER INDEX i_enc SET TABLESPACE enc_ts;
ALTER INDEX i_plain SET TABLESPACE pg_default;

-- Cross-side REINDEX with TABLESPACE succeeds.
REINDEX (TABLESPACE pg_default) INDEX i_enc;
REINDEX (TABLESPACE enc_ts) INDEX i_plain;
REINDEX (TABLESPACE pg_default) TABLE t_enc;
REINDEX (TABLESPACE enc_ts) TABLE t_plain;

-- Helper still reports mismatches because REINDEX moved indexes across sides.
SELECT parent, parent_encrypted, child, child_encrypted, relationship
FROM pg_tde_list_mixed_encryption()
WHERE parent::text IN ('t_enc','t_plain')
ORDER BY parent::text, child::text;

-- REINDEX SCHEMA with TABLESPACE moves indexes across sides, mixed allowed.
REINDEX (TABLESPACE enc_ts) SCHEMA public;
SELECT parent, parent_encrypted, child, child_encrypted, relationship
FROM pg_tde_list_mixed_encryption()
WHERE parent::text IN ('t_enc','t_plain')
ORDER BY parent::text, child::text;

DROP TABLE t_enc;
DROP TABLE t_plain;
DROP TABLESPACE enc_ts;
DROP EXTENSION pg_tde;
