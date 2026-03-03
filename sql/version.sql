SELECT * FROM pg_get_loaded_modules() WHERE file_name IN ('pg_tde.so', 'pg_tde.dylib');
CREATE EXTENSION pg_tde;
SELECT pg_tde_version();
DROP EXTENSION pg_tde;
