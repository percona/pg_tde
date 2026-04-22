-- Cross-tablespace CREATE INDEX is allowed.
-- pg_tde_list_mixed_encryption() reports the resulting mismatches.

\! rm -f '/tmp/pg_tde_prototype_idx.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_prototype_idx.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

SET allow_in_place_tablespaces = true;
CREATE TABLESPACE enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('enc_ts');

CREATE TABLE t_enc (x int) TABLESPACE enc_ts;
CREATE TABLE t_plain (x int);

-- Cross-tablespace indexes succeed (mixed setup).
CREATE INDEX i_enc_in_plain ON t_enc (x) TABLESPACE pg_default;
CREATE INDEX i_plain_in_enc ON t_plain (x) TABLESPACE enc_ts;

-- Same-side indexes also succeed.
CREATE INDEX i_enc_same ON t_enc (x) TABLESPACE enc_ts;
CREATE INDEX i_plain_same ON t_plain (x);

-- Helper lists exactly the two cross-side pairs.
SELECT parent, parent_encrypted, child, child_encrypted, relationship
FROM pg_tde_list_mixed_encryption()
WHERE parent::text IN ('t_enc','t_plain')
ORDER BY parent::text, child::text;

DROP TABLE t_enc;
DROP TABLE t_plain;
DROP TABLESPACE enc_ts;
DROP EXTENSION pg_tde;
