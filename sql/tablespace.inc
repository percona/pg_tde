CREATE EXTENSION pg_tde;

SELECT pg_tde_add_key_provider_file('file-vault','/tmp/pg_tde_test_keyring.per');
SELECT pg_tde_set_principal_key('test-db-principal-key','file-vault');

CREATE TABLE test(num1 bigint, num2 double precision, t text) USING :tde_am;
INSERT INTO test(num1, num2, t)
  SELECT round(random()*100), random(), 'text'
  FROM generate_series(1, 10) s(i);
CREATE INDEX test_idx ON test(num1);

SET allow_in_place_tablespaces = true;
CREATE TABLESPACE test_tblspace LOCATION '';

ALTER TABLE test SET TABLESPACE test_tblspace;
SELECT count(*) FROM test;
ALTER TABLE test SET TABLESPACE pg_default;

REINDEX (TABLESPACE test_tblspace, CONCURRENTLY) TABLE test;
INSERT INTO test VALUES (110, 2);

SELECT * FROM test WHERE num1=110;

DROP TABLE test;
DROP TABLESPACE test_tblspace;
DROP EXTENSION pg_tde;
