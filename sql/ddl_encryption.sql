\! rm -f '/tmp/pg_tde_test_keyring.per'

CREATE EXTENSION pg_tde;

SELECT pg_tde_add_database_key_provider_file('file-vault','/tmp/pg_tde_test_keyring.per');
SELECT pg_tde_create_key_using_database_key_provider('test-db-key','file-vault');
SELECT pg_tde_set_key_using_database_key_provider('test-db-key','file-vault');

-- Failed DDL must not leave its encryption decision behind
CREATE TABLE victim (id serial, a text) USING tde_heap;
CREATE ROLE regress_pg_tde_ddl;
GRANT CREATE ON SCHEMA public TO regress_pg_tde_ddl;
SET ROLE regress_pg_tde_ddl;
BEGIN;
SAVEPOINT s;
ALTER TABLE victim SET ACCESS METHOD heap;
ROLLBACK TO s;
ALTER TABLE IF EXISTS vict__ SET ACCESS METHOD heap;
COMMIT;
RESET ROLE;
SELECT pg_tde_is_encrypted('victim'), pg_tde_is_encrypted('victim_id_seq');

DROP TABLE victim;
REVOKE CREATE ON SCHEMA public FROM regress_pg_tde_ddl;
DROP ROLE regress_pg_tde_ddl;

DROP EXTENSION pg_tde;
