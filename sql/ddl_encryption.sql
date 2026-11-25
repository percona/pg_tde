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

-- DDL in subtransactions inside another DDL statement
CREATE TABLE plain_dup (a int) USING heap;
CREATE SEQUENCE seq_dup;
CREATE FUNCTION nested_ddl() RETURNS event_trigger LANGUAGE plpgsql AS $$
BEGIN
	BEGIN
		CREATE SEQUENCE IF NOT EXISTS nested_seq;
	EXCEPTION WHEN OTHERS THEN NULL;
	END;
	BEGIN
		CREATE SEQUENCE seq_dup;
	EXCEPTION WHEN duplicate_table THEN NULL;
	END;
END
$$;
CREATE EVENT TRIGGER zz_nested_ddl ON ddl_command_start
	WHEN TAG IN ('CREATE TABLE') EXECUTE FUNCTION nested_ddl();
CREATE TABLE enc_nested (a text) USING tde_heap;
CREATE TABLE plain_nested (a text) USING heap;
DROP EVENT TRIGGER zz_nested_ddl;
SELECT pg_tde_is_encrypted('enc_nested'), pg_tde_is_encrypted('plain_nested');
BEGIN;
TRUNCATE enc_nested, plain_nested;
SELECT pg_tde_is_encrypted('enc_nested'), pg_tde_is_encrypted('plain_nested');
COMMIT;
DROP TABLE plain_dup, enc_nested, plain_nested;
DROP SEQUENCE seq_dup, nested_seq;
DROP FUNCTION nested_ddl();

-- Statements without own DDL event in a subtransaction inside DDL
CREATE TABLE enc_trunc (a text) USING tde_heap;
CREATE TABLE plain_trunc (a text) USING heap;
CREATE FUNCTION nested_truncate() RETURNS event_trigger LANGUAGE plpgsql AS $$
BEGIN
	BEGIN
		TRUNCATE enc_trunc, plain_trunc;
	EXCEPTION WHEN OTHERS THEN NULL;
	END;
END
$$;
CREATE EVENT TRIGGER zz_nested_truncate ON ddl_command_start
	WHEN TAG IN ('CREATE TABLE') EXECUTE FUNCTION nested_truncate();
CREATE TABLE enc_outer (a text) USING tde_heap;
SELECT pg_tde_is_encrypted('enc_trunc'), pg_tde_is_encrypted('plain_trunc');
CREATE TABLE plain_outer (a text) USING heap;
SELECT pg_tde_is_encrypted('enc_trunc'), pg_tde_is_encrypted('plain_trunc');
DROP EVENT TRIGGER zz_nested_truncate;
SELECT pg_tde_is_encrypted('enc_outer'), pg_tde_is_encrypted('plain_outer');
DROP TABLE enc_trunc, plain_trunc, enc_outer, plain_outer;
DROP FUNCTION nested_truncate();

-- Statements without own DDL event nested in DDL
CREATE TABLE enc_nest (a text) USING tde_heap;
CREATE INDEX enc_nest_idx ON enc_nest (a);
CREATE TABLE plain_nest (a text) USING heap;
CREATE INDEX plain_nest_idx ON plain_nest (a);
CREATE FUNCTION truncate_nest() RETURNS int LANGUAGE plpgsql AS $$
BEGIN
	TRUNCATE enc_nest, plain_nest;
	RETURN 1;
END
$$;
CREATE TABLE ctas_plain USING heap AS SELECT truncate_nest();
SELECT pg_tde_is_encrypted('enc_nest'), pg_tde_is_encrypted('enc_nest_idx'),
	pg_tde_is_encrypted('plain_nest'), pg_tde_is_encrypted('plain_nest_idx');
CREATE TABLE ctas_enc USING tde_heap AS SELECT truncate_nest();
SELECT pg_tde_is_encrypted('enc_nest'), pg_tde_is_encrypted('enc_nest_idx'),
	pg_tde_is_encrypted('plain_nest'), pg_tde_is_encrypted('plain_nest_idx');
SELECT pg_tde_is_encrypted('ctas_plain'), pg_tde_is_encrypted('ctas_enc');
DROP TABLE enc_nest, plain_nest, ctas_plain, ctas_enc;
DROP FUNCTION truncate_nest();

-- Indexes created by ATTACH PARTITION follow the attached table
CREATE TABLE parted (a int) PARTITION BY RANGE (a);
CREATE INDEX parted_idx ON parted (a);
CREATE TABLE part_plain PARTITION OF parted FOR VALUES FROM (0) TO (10) USING heap;
CREATE TABLE part_enc (a int) USING tde_heap;
ALTER TABLE parted ATTACH PARTITION part_enc FOR VALUES FROM (10) TO (20);
SELECT pg_tde_is_encrypted('part_plain_a_idx'), pg_tde_is_encrypted('part_enc_a_idx');
CREATE TABLE part_sub (a int) PARTITION BY RANGE (a);
CREATE TABLE part_sub_enc PARTITION OF part_sub FOR VALUES FROM (20) TO (30) USING tde_heap;
ALTER TABLE parted ATTACH PARTITION part_sub FOR VALUES FROM (20) TO (30);
SELECT pg_tde_is_encrypted('part_sub_enc_a_idx');

-- ALTER INDEX ... ATTACH PARTITION attaches an existing index, creates nothing
-- ON ONLY skips creating the index on the partitions
CREATE INDEX part_sub_idx ON ONLY part_sub (a);
CREATE INDEX part_sub_enc_idx ON part_sub_enc (a);
ALTER INDEX part_sub_idx ATTACH PARTITION part_sub_enc_idx;
SELECT pg_tde_is_encrypted('part_sub_enc_idx');
DROP TABLE parted;

DROP EXTENSION pg_tde;
