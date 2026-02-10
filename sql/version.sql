SELECT * FROM pg_get_loaded_modules() WHERE file_name = 'pg_tde.so';
CREATE EXTENSION pg_tde;
SELECT pg_tde_version();
DROP EXTENSION pg_tde;
