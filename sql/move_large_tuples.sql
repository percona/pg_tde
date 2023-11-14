-- test pg_tde_move_encrypted_data()
CREATE EXTENSION pg_tde;

CREATE TABLE sbtest2(
	  id SERIAL,
	  k text,
	  PRIMARY KEY (id)
	) USING pg_tde;
alter table sbtest2 alter column k set storage plain;

INSERT INTO sbtest2(k) values(repeat('a', 2500));
INSERT INTO sbtest2(k) values(repeat('b', 2500));
INSERT INTO sbtest2(k) values(repeat('c', 2500));
INSERT INTO sbtest2(k) values(repeat('d', 2500));
INSERT INTO sbtest2(k) values(repeat('e', 2500));

DELETE FROM sbtest2 WHERE id IN (2,3,4);
VACUUM sbtest2;
SELECT * FROM sbtest2;

INSERT INTO sbtest2(k) values(repeat('b', 2500));
INSERT INTO sbtest2(k) values(repeat('c', 2500));
INSERT INTO sbtest2(k) values(repeat('d', 2500));

DELETE FROM sbtest2 where id in (7);
VACUUM sbtest2;

SELECT * FROM sbtest2;

VACUUM FULL sbtest2;
SELECT * FROM sbtest2;

DROP TABLE sbtest2;
DROP EXTENSION pg_tde;
