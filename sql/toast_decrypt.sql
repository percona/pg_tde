CREATE EXTENSION pg_tde;

CREATE TABLE src (f1 text) using pg_tde;
ALTER TABLE src ALTER column f1 SET storage external;
INSERT INTO src values(repeat('abcdeF',1000));
SELECT * FROM src;

DROP TABLE src;

DROP EXTENSION pg_tde;
