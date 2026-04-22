\echo Use "ALTER EXTENSION pg_tde UPDATE TO '2.2'" to load this file. \quit

CREATE FUNCTION pg_tde_mark_tablespace_encrypted(tablespace_name text)
RETURNS void
AS 'MODULE_PATHNAME'
LANGUAGE C STRICT;

CREATE FUNCTION pg_tde_mark_tablespace_decrypted(tablespace_name text)
RETURNS void
AS 'MODULE_PATHNAME'
LANGUAGE C STRICT;

CREATE FUNCTION pg_tde_tablespace_is_encrypted(spc oid)
RETURNS boolean
AS 'MODULE_PATHNAME'
LANGUAGE C STRICT STABLE;

CREATE FUNCTION pg_tde_list_mixed_encryption(
    OUT parent regclass,
    OUT parent_encrypted boolean,
    OUT child regclass,
    OUT child_encrypted boolean,
    OUT relationship text)
RETURNS SETOF record
LANGUAGE sql STABLE
AS $$
    WITH db_default_ts AS (
        SELECT dattablespace AS oid
        FROM pg_database
        WHERE datname = current_database()
    ),
    enc(oid, encrypted) AS (
        SELECT c.oid,
               COALESCE(am.amname = 'tde_heap', false)
               OR pg_tde_tablespace_is_encrypted(
                      COALESCE(NULLIF(c.reltablespace, 0),
                               (SELECT oid FROM db_default_ts)))
        FROM pg_class c
        LEFT JOIN pg_am am ON am.oid = c.relam
        WHERE c.relkind IN ('r','i','I','m','p','t')
    )
    SELECT i.indrelid::regclass,
           ep.encrypted,
           i.indexrelid::regclass,
           ec.encrypted,
           'index'::text
    FROM pg_index i
    JOIN enc ep ON ep.oid = i.indrelid
    JOIN enc ec ON ec.oid = i.indexrelid
    WHERE ep.encrypted IS DISTINCT FROM ec.encrypted
    UNION ALL
    SELECT inh.inhparent::regclass,
           ep.encrypted,
           inh.inhrelid::regclass,
           ec.encrypted,
           'inheritance'::text
    FROM pg_inherits inh
    JOIN enc ep ON ep.oid = inh.inhparent
    JOIN enc ec ON ec.oid = inh.inhrelid
    WHERE ep.encrypted IS DISTINCT FROM ec.encrypted;
$$;

REVOKE ALL ON FUNCTION pg_tde_mark_tablespace_encrypted(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION pg_tde_mark_tablespace_decrypted(text) FROM PUBLIC;
