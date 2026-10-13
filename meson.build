project('pg_tde',
  version: '2.2.2',
  meson_version: '>=0.57',
)

fs = import('fs')

pg_config = find_program(get_option('pg_config'))

if not get_option('tests_only') # skip all build setup, only register tests

bindir = run_command(pg_config, '--bindir', check: true).stdout().strip()
pkglibdir = run_command(pg_config, '--pkglibdir', check: true).stdout().strip()

add_languages('c', 'cpp', native: false)

cmake = import('cmake')

shsplit = find_program(files('shsplit'))

includedir = run_command(pg_config, '--includedir', check: true).stdout().strip()
includedir_server = run_command(pg_config, '--includedir-server', check: true).stdout().strip()
libdir = run_command(pg_config, '--libdir', check: true).stdout().strip()
pkgincludedir = run_command(pg_config, '--pkgincludedir', check: true).stdout().strip()
sharedir = run_command(pg_config, '--sharedir', check: true).stdout().strip()
ldflags = run_command(shsplit, pg_config.full_path(), '--ldflags', check: true).stdout()
ldflags_ex = run_command(shsplit, pg_config.full_path(), '--ldflags_ex', check: true).stdout()
ldflags_sl = run_command(shsplit, pg_config.full_path(), '--ldflags_sl', check: true).stdout()
version = run_command(pg_config, '--version', check: true).stdout().strip()

# Handle empty string until we can use splitlines in Meson 1.2.0
if ldflags == ''
  ldflags = []
else
  ldflags = ldflags.strip().split('\n')
endif
if ldflags_ex == ''
  ldflags_ex = []
else
  ldflags_ex = ldflags_ex.strip().split('\n')
endif
if ldflags_sl == ''
  ldflags_sl = []
else
  ldflags_sl = ldflags_sl.strip().split('\n')
endif

cc = meson.get_compiler('c')

# To make sure we compile code taken from PostgreSQL safely we need to use the
# same functional flags.
#
# These are copied from common_functional_flags in meson.build in PostgreSQL 18.
add_project_arguments(cc.get_supported_arguments([
  '-fno-strict-aliasing',
  '-fwrapv',
  '-fexcess-precision=standard',
]), language: ['c'])

# On Linux EXEC_BACKEND comes from CFLAGS, not headers. Match the server: read
# it from pg_config and apply to every pg_tde target.
pg_cflags = run_command(pg_config, '--cflags', check: true).stdout().split()
pg_cppflags = run_command(pg_config, '--cppflags', check: true).stdout().split()
if '-DEXEC_BACKEND' in pg_cflags or '-DEXEC_BACKEND' in pg_cppflags
  message('PostgreSQL was built with EXEC_BACKEND; enabling it for pg_tde')
  add_project_arguments('-DEXEC_BACKEND', language: ['c'])
endif

# TODO: Why does it seems like they sometimes are in pkglibdir and other times in libdir?
pgport = cc.find_library('pgport', dirs: [pkglibdir, libdir], static: true)
pgcommon = cc.find_library('pgcommon', dirs: [pkglibdir, libdir], static: true)
pgfeutils = cc.find_library('pgfeutils', dirs: [pkglibdir, libdir], static: true)

pq = cc.find_library('pq', dirs: [libdir])
crypto = dependency('libcrypto')
ssl = dependency('libssl')
curl = dependency('libcurl')
lz4 = dependency('liblz4', required: false)
z = dependency('zlib')
zstd = dependency('libzstd', required: false)

major_version = version.split(' ')[1].split('.')[0].split('beta')[0].split('rc')[0].to_int()

fetools = 'fetools/pg@0@'.format(major_version)

incdirs = include_directories(
  'src/include',
  fetools / 'include',
  includedir_server,
  includedir,
  pkgincludedir / 'internal',
)

backend_link_args = ldflags + ldflags_sl
frontend_link_args = ldflags + ldflags_ex

if host_machine.system() == 'darwin'
  backend_link_args += ['-bundle_loader', bindir / 'postgres']
endif

install_data(
  'pg_tde.control',
  'pg_tde--1.0.sql',
  'pg_tde--1.0--2.0.sql',
  'pg_tde--2.0--2.1.sql',
  'pg_tde--2.1--2.2.sql',
  install_dir: sharedir / 'extension',
)

kmip_cmake_opts = cmake.subproject_options()
kmip_cmake_opts.add_cmake_defines({
  'BUILD_TESTS': false,
  'BUILD_KMIP_TESTS': false,
  'BUILD_DOCS': false,
})
kmip_cmake_opts.set_install(false)
# libkmip is a vendored external dependency. Don't impose our -Dwerror=true on
# it: its own warnings (e.g. -Woverloaded-virtual on newer compilers) must not
# fail our build. -Wno-error is appended after meson's injected -Werror.
kmip_cmake_opts.append_compile_args('c', '-Wno-error')
kmip_cmake_opts.append_compile_args('cpp', '-Wno-error')
kmip_subproject = cmake.subproject('libkmip', options: kmip_cmake_opts)
kmipclient = kmip_subproject.dependency('kmipclient')
kmipcore = kmip_subproject.dependency('kmipcore')

shared_module('pg_tde',
  files(
    'src/access/pg_tde_tdemap.c',
    'src/access/pg_tde_xlog.c',
    'src/access/pg_tde_xlog_keys.c',
    'src/access/pg_tde_xlog_smgr.c',
    'src/catalog/tde_keyring.c',
    'src/catalog/tde_keyring_parse_opts.c',
    'src/catalog/tde_principal_key.c',
    'src/common/pg_tde_utils.c',
    'src/encryption/enc_aes.c',
    'src/encryption/enc_tde.c',
    'src/keyring/keyring_api.c',
    'src/keyring/keyring_curl.c',
    'src/keyring/keyring_file.c',
    'src/keyring/keyring_kmip.cpp',
    'src/keyring/keyring_vault.c',
    'src/pg_tde.c',
    'src/pg_tde_event_capture.c',
    'src/pg_tde_guc.c',
    'src/smgr/pg_tde_smgr.c',
  ),
  override_options: ['cpp_std=c++20'],
  include_directories: incdirs,
  install: true,
  install_dir: pkglibdir,
  dependencies: [crypto, ssl, curl, kmipclient, kmipcore],
  name_prefix: '',
  link_args: backend_link_args,
  link_language: 'cpp',
)

pg_tde_frontend = static_library('pg_tde_frontend',
  files(
    'src/pg_tde_fe.c',
    'src/access/pg_tde_tdemap.c',
    'src/access/pg_tde_xlog.c',
    'src/access/pg_tde_xlog_keys.c',
    'src/catalog/tde_keyring.c',
    'src/catalog/tde_keyring_parse_opts.c',
    'src/catalog/tde_principal_key.c',
    'src/common/pg_tde_utils.c',
    'src/encryption/enc_aes.c',
    'src/encryption/enc_tde.c',
    'src/keyring/keyring_api.c',
    'src/keyring/keyring_curl.c',
    'src/keyring/keyring_file.c',
    'src/keyring/keyring_kmip.cpp',
    'src/keyring/keyring_vault.c',
  ),
  c_args: ['-DFRONTEND'],
  cpp_args: ['-DFRONTEND'],
  override_options: ['cpp_std=c++20'],
  dependencies: [pgfeutils, pgcommon, pgport, curl, crypto, ssl, kmipclient, kmipcore],
  include_directories: incdirs,
)

pg_tde_frontend_xlog = static_library('pg_tde_frontend_xlog',
  files(
    'src/access/pg_tde_xlog_smgr.c',
    fetools / 'xlogreader.c',
  ),
  dependencies: [lz4, zstd],
  c_args: ['-DFRONTEND'],
  include_directories: incdirs,
)

executable('pg_tde_change_key_provider',
  files('src/bin/pg_tde_change_key_provider.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_archive_decrypt',
  files('src/bin/pg_tde_archive_decrypt.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_restore_encrypt',
  files('src/bin/pg_tde_restore_encrypt.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_upgrade',
  files('src/bin/pg_tde_upgrade.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  dependencies: [pgcommon, pgport],
  link_args: frontend_link_args,
)

if major_version >= 18
  bb_sources = files(
    fetools / 'pg_basebackup/receivelog.c',
    fetools / 'pg_basebackup/streamutil.c',
    fetools / 'pg_basebackup/walmethods.c',
    fetools / 'pg_basebackup/pg_basebackup.c',
    fetools / 'pg_basebackup/astreamer_inject.c',
  )
else
  bb_sources = files(
     fetools / 'pg_basebackup/receivelog.c',
     fetools / 'pg_basebackup/streamutil.c',
     fetools / 'pg_basebackup/walmethods.c',
     fetools / 'pg_basebackup/pg_basebackup.c',
     fetools / 'pg_basebackup/bbstreamer_file.c',
     fetools / 'pg_basebackup/bbstreamer_gzip.c',
     fetools / 'pg_basebackup/bbstreamer_inject.c',
     fetools / 'pg_basebackup/bbstreamer_lz4.c',
     fetools / 'pg_basebackup/bbstreamer_tar.c',
     fetools / 'pg_basebackup/bbstreamer_zstd.c',
  )
endif

executable('pg_tde_basebackup',
  bb_sources,
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  install_rpath: libdir,
  dependencies: [pq, z],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_checksums',
  files(
    fetools / 'pg_checksums/pg_checksums.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_resetwal',
  files(
    fetools / 'pg_resetwal/pg_resetwal.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

executable('pg_tde_rewind',
  files(
    fetools / 'pg_rewind/datapagemap.c',
    fetools / 'pg_rewind/file_ops.c',
    fetools / 'pg_rewind/filemap.c',
    fetools / 'pg_rewind/libpq_source.c',
    fetools / 'pg_rewind/local_source.c',
    fetools / 'pg_rewind/parsexlog.c',
    fetools / 'pg_rewind/pg_rewind.c',
    fetools / 'pg_rewind/tde_ops.c',
    fetools / 'pg_rewind/timeline.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  install_rpath: libdir,
  dependencies: [pq],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

wd_sources = [
  fetools / 'pg_waldump/compat.c',
  fetools / 'pg_waldump/pg_waldump.c',
  fetools / 'pg_waldump/rmgrdesc.c',
  fetools / 'rmgrdesc/brindesc.c',
  fetools / 'rmgrdesc/clogdesc.c',
  fetools / 'rmgrdesc/committsdesc.c',
  fetools / 'rmgrdesc/dbasedesc.c',
  fetools / 'rmgrdesc/genericdesc.c',
  fetools / 'rmgrdesc/gindesc.c',
  fetools / 'rmgrdesc/gistdesc.c',
  fetools / 'rmgrdesc/hashdesc.c',
  fetools / 'rmgrdesc/heapdesc.c',
  fetools / 'rmgrdesc/logicalmsgdesc.c',
  fetools / 'rmgrdesc/mxactdesc.c',
  fetools / 'rmgrdesc/nbtdesc.c',
  fetools / 'rmgrdesc/relmapdesc.c',
  fetools / 'rmgrdesc/replorigindesc.c',
  fetools / 'rmgrdesc/rmgrdesc_utils.c',
  fetools / 'rmgrdesc/seqdesc.c',
  fetools / 'rmgrdesc/smgrdesc.c',
  fetools / 'rmgrdesc/spgdesc.c',
  fetools / 'rmgrdesc/standbydesc.c',
  fetools / 'rmgrdesc/tblspcdesc.c',
  fetools / 'rmgrdesc/xactdesc.c',
  fetools / 'rmgrdesc/xlogdesc.c',
  fetools / 'xlogstats.c',
]

if major_version >= 19
  wd_sources += [fetools / 'pg_waldump/archive_waldump.c']
endif

executable('pg_tde_waldump',
  files(wd_sources),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  c_args: ['-DFRONTEND'],
  dependencies: [z],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
  link_args: frontend_link_args,
  link_language: 'cpp',
)

endif # not tests_only

stormweaver = find_program(get_option('stormweaver'), required: false)
if not stormweaver.found() and get_option('tests_only')
  error('stormweaver not found; install it or pass -Dstormweaver=/path/to/stormweaver')
endif

pytest_files = [
  'tests/pgtde/test_providers.py',
  'tests/t/test_access_control.py',
  'tests/t/test_alter_index.py',
  'tests/t/test_basebackup_default_key.py',
  'tests/t/test_basic.py',
  'tests/t/test_change_access_method.py',
  'tests/t/test_change_key_provider.py',
  'tests/t/test_crash_recovery.py',
  'tests/t/test_create_database.py',
  'tests/t/test_default_principal_key.py',
  'tests/t/test_delete_principal_key.py',
  'tests/t/test_insert_update_delete.py',
  'tests/t/test_key_provider.py',
  'tests/t/test_key_rotate_tablespace.py',
  'tests/t/test_key_validation.py',
  'tests/t/test_keys_update.py',
  'tests/t/test_kmip.py',
  'tests/t/test_partition_table.py',
  'tests/t/test_pg_basebackup.py',
  'tests/t/test_pg_rewind_basic.py',
  'tests/t/test_pg_rewind_databases.py',
  'tests/t/test_pg_rewind_enc_copy_blocks.py',
  'tests/t/test_pg_rewind_enc_ext_tablespace.py',
  'tests/t/test_pg_rewind_enc_fsm.py',
  'tests/t/test_pg_rewind_enc_keep_archive_wal.py',
  'tests/t/test_pg_rewind_enc_keep_wal_seg.py',
  'tests/t/test_pg_rewind_enc_unchanged_rel.py',
  'tests/t/test_pg_rewind_extrafiles.py',
  'tests/t/test_pg_rewind_growing_files.py',
  'tests/t/test_pg_rewind_keep_recycled_wals.py',
  'tests/t/test_pg_rewind_min_recovery_point.py',
  'tests/t/test_pg_rewind_options.py',
  'tests/t/test_pg_rewind_pg_xlog_symlink.py',
  'tests/t/test_pg_rewind_same_timeline.py',
  'tests/t/test_pg_tde_change_key_provider.py',
  'tests/t/test_pg_tde_checksums.py',
  'tests/t/test_pg_tde_is_encrypted.py',
  'tests/t/test_pg_tde_upgrade.py',
  'tests/t/test_pg_waldump_basic.py',
  'tests/t/test_pg_waldump_fullpage.py',
  'tests/t/test_pg_waldump_tde_rmgr.py',
  'tests/t/test_recreate_storage.py',
  'tests/t/test_relocate.py',
  'tests/t/test_replication.py',
  'tests/t/test_reuse_relfilenode_in_cache.py',
  'tests/t/test_rotate_key.py',
  'tests/t/test_tablespace.py',
  'tests/t/test_tde_heap.py',
  'tests/t/test_tde_heap_aes_256.py',
  'tests/t/test_toast_decrypt.py',
  'tests/t/test_unlogged_tables.py',
  'tests/t/test_vault_v2.py',
  'tests/t/test_version.py',
  'tests/t/test_wal_archiving.py',
  'tests/t/test_wal_archiving_symlink.py',
  'tests/t/test_wal_encrypt.py',
  'tests/t/test_wal_key_tli.py',
]

if stormweaver.found()
  pytest_env = environment()
  pytest_env.set('STORMWEAVER_PG_CONFIG', pg_config.full_path())

  foreach f : pytest_files
    pytest_stem = fs.stem(fs.name(f))
    if pytest_stem.startswith('test_')
      pytest_stem = pytest_stem.substring(5)
    endif
    pytest_name = fs.parent(f) / pytest_stem
    pytest_args = ['test', meson.project_source_root() / f, '-q', '--pg-config', pg_config.full_path()]
    test(pytest_name, stormweaver,
      suite: 'fast',
      env: pytest_env,
      workdir: meson.project_build_root(),
      timeout: 1800,
      args: pytest_args,
    )
    test(pytest_name + '/full', stormweaver,
      suite: 'full',
      env: pytest_env,
      workdir: meson.project_build_root(),
      timeout: 3600,
      args: pytest_args + ['--full'],
    )
  endforeach

  # plain `meson test` runs the fast suite only
  add_test_setup('default', exclude_suites: ['full'], is_default: true)
else
  warning('stormweaver not found; pytest suite not registered (pass -Dstormweaver=/path/to/stormweaver)')
endif
