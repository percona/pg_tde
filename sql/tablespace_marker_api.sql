-- Public API surface for pg_tde_mark_tablespace_{encrypted,decrypted}.

\! rm -f '/tmp/pg_tde_marker_api.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('fv','/tmp/pg_tde_marker_api.per');
SELECT pg_tde_create_key_using_database_key_provider('k','fv');
SELECT pg_tde_set_key_using_database_key_provider('k','fv');

-- 1. Non-existent name.
SELECT pg_tde_mark_tablespace_encrypted('does_not_exist');

-- 2-4. pg_default / pg_global rejected (both variants).
SELECT pg_tde_mark_tablespace_encrypted('pg_default');
SELECT pg_tde_mark_tablespace_encrypted('pg_global');
SELECT pg_tde_mark_tablespace_decrypted('pg_default');
SELECT pg_tde_mark_tablespace_decrypted('pg_global');

-- Setup: create an empty tablespace owned by the running user.
SET allow_in_place_tablespaces = true;
CREATE TABLESPACE marker_ts LOCATION '';

-- 5. Inside transaction block — rejected.
BEGIN;
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');
ROLLBACK;

-- 6. Inside DO block (implicit tx) — rejected.
DO $$ BEGIN PERFORM pg_tde_mark_tablespace_encrypted('marker_ts'); END $$;

-- 6b. Inside CALL of a procedure body (nonatomic SPI ctx) — rejected.
CREATE PROCEDURE marker_proc() LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_tde_mark_tablespace_encrypted('marker_ts');
END $$;
CALL marker_proc();
DROP PROCEDURE marker_proc();

-- 7a. Non-owner, no EXECUTE grant: SQL-level EXECUTE check rejects.
CREATE ROLE marker_norole;
SET ROLE marker_norole;
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');  -- ERROR: permission denied for function
RESET ROLE;

-- 7b. Non-owner, WITH EXECUTE granted: C-level ownercheck rejects.
GRANT EXECUTE ON FUNCTION pg_tde_mark_tablespace_encrypted(text) TO marker_norole;
GRANT EXECUTE ON FUNCTION pg_tde_mark_tablespace_decrypted(text) TO marker_norole;
SET ROLE marker_norole;
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');  -- ERROR: must be owner of tablespace
RESET ROLE;
REVOKE EXECUTE ON FUNCTION pg_tde_mark_tablespace_encrypted(text) FROM marker_norole;
REVOKE EXECUTE ON FUNCTION pg_tde_mark_tablespace_decrypted(text) FROM marker_norole;

-- 8-9. Owner (here superuser = owner by default) succeeds.
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');

-- 10. Idempotent NOTICE.
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');

-- 11. Round-trip back to decrypted.
SELECT pg_tde_mark_tablespace_decrypted('marker_ts');

-- 12. Idempotent the other direction.
SELECT pg_tde_mark_tablespace_decrypted('marker_ts');

-- 13. Probe via CREATE TABLE + pg_tde_is_encrypted.
CREATE TABLE t_probe (x int) TABLESPACE marker_ts;
SELECT pg_tde_is_encrypted('t_probe');
DROP TABLE t_probe;

-- Mark encrypted and probe: should behave as encrypted tablespace.
SELECT pg_tde_mark_tablespace_encrypted('marker_ts');
CREATE TABLE t_probe_enc (x int) TABLESPACE marker_ts;
SELECT pg_tde_is_encrypted('t_probe_enc');
DROP TABLE t_probe_enc;
SELECT pg_tde_mark_tablespace_decrypted('marker_ts');

DROP TABLESPACE marker_ts;
DROP ROLE marker_norole;
DROP EXTENSION pg_tde;
