-- We test cache so AM doesn't matter
-- Just checking there are no mem debug WARNINGs during the cache population

CREATE EXTENSION pg_tde;

SELECT pg_tde_add_key_provider_file('file-vault','/tmp/pg_tde_test_keyring.per');
SELECT pg_tde_set_principal_key('test-db-principal-key','file-vault');

do $$
    DECLARE idx integer;
begin
    for idx in 0..700 loop
        EXECUTE format('CREATE TABLE t%s (c1 int) USING tde_heap_basic', idx);
    end loop;
end; $$;

DROP EXTENSION pg_tde cascade;
