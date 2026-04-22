-- Prototype rule: any non-default tablespace encrypts content, regardless of AM.

\! rm -f '/tmp/pg_tde_prototype_keyring.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('file-vault','/tmp/pg_tde_prototype_keyring.per');
SELECT pg_tde_create_key_using_database_key_provider('test-db-key','file-vault');
SELECT pg_tde_set_key_using_database_key_provider('test-db-key','file-vault');

SET allow_in_place_tablespaces = true;
CREATE TABLESPACE enc_ts LOCATION '';
SELECT pg_tde_mark_tablespace_encrypted('enc_ts');

-- Plain AM in custom tablespace: reported as encrypted.
CREATE TABLE t_plain_enc (x int) TABLESPACE enc_ts;
SELECT pg_tde_is_encrypted('t_plain_enc');

-- Plain AM in pg_default: reported as not encrypted.
CREATE TABLE t_plain_plain (x int);
SELECT pg_tde_is_encrypted('t_plain_plain');

DROP TABLE t_plain_enc;
DROP TABLE t_plain_plain;
DROP TABLESPACE enc_ts;
DROP EXTENSION pg_tde;
