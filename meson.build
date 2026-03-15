project('pg_tde',
  ['c'],
  version: '2.1.2',
)

pg_config = find_program(get_option('pg_config'))

bindir = run_command(pg_config, '--bindir', check: true).stdout().strip()
includedir = run_command(pg_config, '--includedir', check: true).stdout().strip()
includedir_server = run_command(pg_config, '--includedir-server', check: true).stdout().strip()
libdir = run_command(pg_config, '--libdir', check: true).stdout().strip()
pkgincludedir = run_command(pg_config, '--pkgincludedir', check: true).stdout().strip()
pkglibdir = run_command(pg_config, '--pkglibdir', check: true).stdout().strip()
sharedir = run_command(pg_config, '--sharedir', check: true).stdout().strip()
version = run_command(pg_config, '--version', check: true).stdout().strip()

# TODO: Do something about flags?

cc = meson.get_compiler('c')

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

major_version = version.split(' ')[1].split('.')[0].to_int()

fetools = 'fetools/pg@0@'.format(major_version)

incdirs = include_directories(
  'src/include',
  'src/libkmip/libkmip/include',
  fetools / 'include',
  includedir_server,
  includedir,
  pkgincludedir / 'internal',
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

if major_version == 18
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
  dependencies: [pq, z],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
)

executable('pg_tde_checksums',
  files(
    fetools / 'pg_checksums/pg_checksums.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend],
)

executable('pg_tde_resetwal',
  files(
    fetools / 'pg_resetwal/pg_resetwal.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
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
    fetools / 'pg_rewind/timeline.c',
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  dependencies: [pq],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
)

executable('pg_tde_waldump',
  files(
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
  ),
  include_directories: incdirs,
  install: true,
  install_dir: bindir,
  c_args: ['-DFRONTEND'],
  link_with: [pg_tde_frontend, pg_tde_frontend_xlog],
)
