-- Principal key required to create anything in an encrypted tablespace.

CREATE EXTENSION pg_tde;
SET allow_in_place_tablespaces = true;
CREATE TABLESPACE enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('enc_ts');

-- No principal key configured yet: CREATE in encrypted ts must fail.
CREATE TABLE t_no_key (x int) TABLESPACE enc_ts;

-- CTAS variant:
CREATE TABLE t_ctas_no_key TABLESPACE enc_ts AS SELECT 1;

-- Matview variant:
CREATE MATERIALIZED VIEW mv_no_key TABLESPACE enc_ts AS SELECT 1;

-- Plain tablespace still allowed without principal key:
CREATE TABLE t_plain_ok (x int);

-- Now configure principal key and retry:
\! rm -f '/tmp/pg_tde_prototype_pk.per'
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_prototype_pk.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

CREATE TABLE t_with_key (x int) TABLESPACE enc_ts;

DROP TABLE t_with_key;
DROP TABLE t_plain_ok;
DROP TABLESPACE enc_ts;
DROP EXTENSION pg_tde;
