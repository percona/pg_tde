-- enforce_encryption accepts tde_heap OR encrypted tablespace.

\! rm -f '/tmp/pg_tde_prototype_enf.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_prototype_enf.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

SET allow_in_place_tablespaces = true;
CREATE TABLESPACE enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('enc_ts');

SET pg_tde.enforce_encryption = on;

-- Rejected: plain heap in plain tablespace.
CREATE TABLE t_bad (x int);

-- Accepted: tde_heap in plain tablespace.
CREATE TABLE t_ok_am (x int) USING tde_heap;

-- Accepted: plain heap in encrypted tablespace.
CREATE TABLE t_ok_ts (x int) TABLESPACE enc_ts;

-- Accepted: tde_heap in encrypted tablespace.
CREATE TABLE t_ok_both (x int) USING tde_heap TABLESPACE enc_ts;

SET pg_tde.enforce_encryption = off;

DROP TABLE t_ok_am;
DROP TABLE t_ok_ts;
DROP TABLE t_ok_both;
DROP TABLESPACE enc_ts;
DROP EXTENSION pg_tde;
