-- Fix 1+2 coverage: ALTER TABLE SET TABLESPACE interactions with principal key
-- and enforce_encryption.

CREATE EXTENSION pg_tde;
SET allow_in_place_tablespaces = true;
CREATE TABLESPACE alter_enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('alter_enc_ts');

-- (a) No principal key: ALTER into encrypted tablespace rejected at DDL time.
CREATE TABLE t_alter_no_key (x int);  -- in pg_default, plain
ALTER TABLE t_alter_no_key SET TABLESPACE alter_enc_ts;  -- expected ERROR principal key

-- Configure a key.
\! rm -f '/tmp/pg_tde_prototype_alter_ts.per'
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_prototype_alter_ts.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

-- (b) With key: ALTER into encrypted tablespace succeeds.
ALTER TABLE t_alter_no_key SET TABLESPACE alter_enc_ts;

-- (c) With key and enforce_encryption on: ALTER plain->encrypted still succeeds.
CREATE TABLE t_alter_enforce (x int);  -- plain, in pg_default
SET pg_tde.enforce_encryption = on;
ALTER TABLE t_alter_enforce SET TABLESPACE alter_enc_ts;
SET pg_tde.enforce_encryption = off;

DROP TABLE t_alter_no_key;
DROP TABLE t_alter_enforce;
DROP TABLESPACE alter_enc_ts;
DROP EXTENSION pg_tde;
