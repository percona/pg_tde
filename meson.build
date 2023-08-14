pg_tde_sources = files(
        'pg_tde/pg_tdeam.c',
        'pg_tde/pg_tdeam_handler.c',
        'pg_tde/pg_tdeam_visibility.c',
        'pg_tde/pg_tdetoast.c',
        'pg_tde/pg_tde_io.c',
        'pg_tde/pg_tde_prune.c',
        'pg_tde/pg_tde_rewrite.c',
        'pg_tde/pg_tde_vacuumlazy.c',
        'pg_tde/pg_tde_visibilitymap.c',
)

incdir = include_directories('.')

pg_tde = shared_module('pg_tde',
  pg_tde_sources,
  c_pch: pch_postgres_h,
  kwargs: contrib_mod_args,
  include_directories: incdir,
)
contrib_targets += pg_tde

install_data(
  'pg_tde.control',
  'pg_tde--1.0.sql',
  kwargs: contrib_data_args,
)
