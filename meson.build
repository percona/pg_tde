project('pg_tde',
  ['c'],
  version: '2.1.2',
  meson_version: '>=0.53',
)

pg_config = find_program(get_option('pg_config'))

bindir = run_command(pg_config, '--bindir', check: true).stdout().strip()
includedir_server = run_command(pg_config, '--includedir-server', check: true).stdout().strip()
libdir = run_command(pg_config, '--libdir', check: true).stdout().strip()
pkglibdir = run_command(pg_config, '--pkglibdir', check: true).stdout().strip()
sharedir = run_command(pg_config, '--sharedir', check: true).stdout().strip()
version = run_command(pg_config, '--version', check: true).stdout().strip()

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

# TODO: Why does it seems like they sometimes are in pkglibdir and other times in libdir?
pgport = cc.find_library('pgport', dirs: [pkglibdir, libdir], static: true)
pgcommon = cc.find_library('pgcommon', dirs: [pkglibdir, libdir], static: true)
pgfeutils = cc.find_library('pgfeutils', dirs: [pkglibdir, libdir], static: true)

crypto = dependency('libcrypto')
ssl = dependency('libssl')
curl = dependency('libcurl')
lz4 = dependency('liblz4', required: false)
z = dependency('zlib')
zstd = dependency('libzstd', required: false)

incdirs = include_directories(
  'src/include',
  'src/libkmip/libkmip/include',
  includedir_server,
)

install_data(
  'pg_tde.control',
  'pg_tde--1.0.sql',
  'pg_tde--1.0--2.0.sql',
  'pg_tde--2.0--2.1.sql',
  install_dir: sharedir / 'extension',
)

kmip = static_library('kmip',
  files(
    'src/libkmip/libkmip/src/kmip.c',
    'src/libkmip/libkmip/src/kmip_bio.c',
    'src/libkmip/libkmip/src/kmip_locate.c',
    'src/libkmip/libkmip/src/kmip_memset.c',
  ),
  c_args: ['-w'], # This is a 3rd party, disable warnings completely
  include_directories: incdirs,
)

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
    'src/keyring/keyring_kmip.c',
    'src/keyring/keyring_kmip_impl.c',
    'src/keyring/keyring_vault.c',
    'src/pg_tde.c',
    'src/pg_tde_event_capture.c',
    'src/pg_tde_guc.c',
    'src/smgr/pg_tde_smgr.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: pkglibdir,
  dependencies: [crypto, ssl, curl],
  name_prefix: '',
  link_with: [kmip],
)

pg_tde_frontend = static_library('pg_tde_frontend',
  files(
    'src/access/pg_tde_tdemap.c',
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
    'src/keyring/keyring_kmip.c',
    'src/keyring/keyring_kmip_impl.c',
    'src/keyring/keyring_vault.c',
  ),
  c_args: ['-DFRONTEND'],
  dependencies: [pgfeutils, pgcommon, pgport, curl, crypto, ssl],
  include_directories: incdirs,
  link_with: [kmip],
)

pg_tde_frontend_xlog = static_library('pg_tde_frontend_xlog',
  files(
    'src/access/pg_tde_xlog_smgr.c',
    fetools / 'xlogreader.c',
  ),
  dependencies: [lz4, zstd],
  c_args: ['-DFRONTEND'],
  include_directories: incdirs,
  link_with: [kmip],
)

executable('pg_tde_change_key_provider',
  files('src/bin/pg_tde_change_key_provider.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend],
)

executable('pg_tde_archive_decrypt',
  files('src/bin/pg_tde_archive_decrypt.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
)

executable('pg_tde_restore_encrypt',
  files('src/bin/pg_tde_restore_encrypt.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
)

executable('pg_tde_upgrade',
  files('src/bin/pg_tde_upgrade.c'),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  dependencies: [pgcommon, pgport],
)
