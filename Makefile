PGFILEDESC = "pg_tde access method"
MODULE_big = pg_tde
EXTENSION = pg_tde
DATA = pg_tde--1.0--2.0.sql pg_tde--1.0.sql

# Since meson supports skipping test suites this is a make only feature
ifndef TDE_MODE
REGRESS_OPTS = --temp-config $(top_srcdir)/contrib/pg_tde/pg_tde.conf
REGRESS = \
	access_control \
	alter_index \
	cache_alloc \
	change_access_method \
	create_database \
	default_principal_key \
	delete_principal_key \
	insert_update_delete \
	key_provider \
	kmip_test \
	partition_table \
	pg_tde_is_encrypted \
	recreate_storage \
	relocate \
	tablespace \
	toast_decrypt \
	vault_v2_test \
	version
TAP_TESTS = 1
endif

FETOOLS = fetools/pg$(MAJORVERSION)

KMIP_OBJS = \
	src/libkmip/libkmip/src/kmip.o \
	src/libkmip/libkmip/src/kmip_bio.o \
	src/libkmip/libkmip/src/kmip_locate.o \
	src/libkmip/libkmip/src/kmip_memset.o

OBJS = \
	src/encryption/enc_tde.o \
	src/encryption/enc_aes.o \
	src/access/pg_tde_tdemap.o \
	src/access/pg_tde_xlog.o \
	src/access/pg_tde_xlog_keys.o \
	src/access/pg_tde_xlog_smgr.o \
	src/keyring/keyring_curl.o \
	src/keyring/keyring_file.o \
	src/keyring/keyring_vault.o \
	src/keyring/keyring_kmip.o \
	src/keyring/keyring_kmip_impl.o \
	src/keyring/keyring_api.o \
	src/catalog/tde_keyring.o \
	src/catalog/tde_keyring_parse_opts.o \
	src/catalog/tde_principal_key.o \
	src/common/pg_tde_utils.o \
	src/smgr/pg_tde_smgr.o \
	src/pg_tde_event_capture.o \
	src/pg_tde_guc.o \
	src/pg_tde.o \
	$(KMIP_OBJS)

TDE_XLOG_OBJS = src/access/pg_tde_xlog_smgr.frontend

TDE_OBJS = \
	src/access/pg_tde_tdemap.frontend \
	src/catalog/tde_keyring.frontend \
	src/access/pg_tde_xlog_keys.frontend \
	src/catalog/tde_keyring_parse_opts.frontend \
	src/catalog/tde_principal_key.frontend \
	src/common/pg_tde_utils.frontend \
	src/encryption/enc_aes.frontend \
	src/encryption/enc_tde.frontend \
	src/keyring/keyring_api.frontend \
	src/keyring/keyring_curl.frontend \
	src/keyring/keyring_file.frontend \
	src/keyring/keyring_vault.frontend \
	src/libkmip/libkmip/src/kmip.frontend \
	src/libkmip/libkmip/src/kmip_bio.frontend \
	src/libkmip/libkmip/src/kmip_locate.frontend \
	src/libkmip/libkmip/src/kmip_memset.frontend \
	src/keyring/keyring_kmip.frontend \
	src/keyring/keyring_kmip_impl.frontend

BBOBJS = \
	$(FETOOLS)/pg_basebackup/receivelog.o \
	$(FETOOLS)/pg_basebackup/streamutil.o \
	$(FETOOLS)/pg_basebackup/walmethods.o \
	$(FETOOLS)/pg_basebackup/pg_basebackup.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_file.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_gzip.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_inject.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_lz4.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_tar.o \
	$(FETOOLS)/pg_basebackup/bbstreamer_zstd.o

RWOBJS = \
	$(FETOOLS)/pg_rewind/datapagemap.o \
	$(FETOOLS)/pg_rewind/file_ops.o \
	$(FETOOLS)/pg_rewind/filemap.o \
	$(FETOOLS)/pg_rewind/libpq_source.o \
	$(FETOOLS)/pg_rewind/local_source.o \
	$(FETOOLS)/pg_rewind/parsexlog.o \
	$(FETOOLS)/pg_rewind/pg_rewind.o \
	$(FETOOLS)/pg_rewind/timeline.o

RMGRDESCSOURCES = $(sort $(wildcard $(FETOOLS)/rmgrdesc/*desc*.c))
RMGRDESCOBJS = $(patsubst %.c,%.o,$(RMGRDESCSOURCES))

WDOBJS = \
	$(FETOOLS)/pg_waldump/compat.o \
	$(FETOOLS)/pg_waldump/pg_waldump.o \
	$(FETOOLS)/pg_waldump/rmgrdesc.o \
	$(RMGRDESCOBJS)

SCRIPTS_built = \
	src/bin/pg_tde_archive_decrypt \
	src/bin/pg_tde_change_key_provider \
	src/bin/pg_tde_restore_encrypt \
	$(FETOOLS)/pg_tde_basebackup \
	$(FETOOLS)/pg_tde_checksums \
	$(FETOOLS)/pg_tde_resetwal \
	$(FETOOLS)/pg_tde_rewind \
	$(FETOOLS)/pg_tde_waldump

EXTRA_INSTALL = contrib/pg_buffercache contrib/test_decoding
EXTRA_CLEAN = \
	src/bin/pg_tde_archive_decrypt.o \
	src/bin/pg_tde_change_key_provider.o \
	src/bin/pg_tde_restore_encrypt.o \
	$(FETOOLS)/xlogreader.o \
	$(FETOOLS)/xlogstats.o \
	$(TDE_XLOG_OBJS) \
	$(TDE_OBJS) \
	$(BBOBJS) \
	$(FETOOLS)/pg_checksums/pg_checksums.o \
	$(FETOOLS)/pg_resetwal/pg_resetwal.o \
	$(RWOBJS) \
	$(WDOBJS) \
	libtde.a \
	libtdexlog.a

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
PG_CPPFLAGS = -Isrc/include -Isrc/libkmip/libkmip/include -I$(FETOOLS)/include -I$(includedir)
include $(PGXS)

SHLIB_LINK = -lcurl -lcrypto -lssl
LDFLAGS_EX = -Lsrc/fe_utils -lcurl -lcrypto -lssl -lz -lzstd -llz4 -lpgfeutils $(libpq_pgport)

$(KMIP_OBJS): CFLAGS += -w # This is a 3rd party, disable warnings completely

src/bin/pg_tde_change_key_provider: src/bin/pg_tde_change_key_provider.o libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

src/bin/pg_tde_archive_decrypt: src/bin/pg_tde_archive_decrypt.o $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

src/bin/pg_tde_restore_encrypt: src/bin/pg_tde_restore_encrypt.o $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/pg_tde_basebackup: $(BBOBJS) $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/pg_tde_checksums: $(FETOOLS)/pg_checksums/pg_checksums.o libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/pg_tde_resetwal: $(FETOOLS)/pg_resetwal/pg_resetwal.o $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/pg_tde_rewind: $(RWOBJS) $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/pg_tde_waldump: $(WDOBJS) $(FETOOLS)/xlogstats.o $(FETOOLS)/xlogreader.o libtdexlog.a libtde.a
	$(CC) $(CFLAGS) $^ $(PG_LIBS_INTERNAL) $(LDFLAGS) $(LDFLAGS_EX) $(PG_LIBS) $(LIBS) -o $@$(X)

$(FETOOLS)/%.o: CFLAGS += -DFRONTEND

%.frontend: %.c
	$(CC) $(CPPFLAGS) -DFRONTEND -I$(top_srcdir)/contrib/pg_tde/src/include -I$(top_srcdir)/contrib/pg_tde/src/libkmip/libkmip/include -c $< -o $@

libtde.a: $(TDE_OBJS)
	$(AR) $(AROPT) $@ $^

libtdexlog.a: $(TDE_XLOG_OBJS)
	$(AR) $(AROPT) $@ $^

# Fetches typedefs list for PostgreSQL core and merges it with typedefs defined in this project.
# https://wiki.postgresql.org/wiki/Running_pgindent_on_non-core_code_or_development_code
update-typedefs:
	wget -q -O - "https://buildfarm.postgresql.org/cgi-bin/typedefs.pl?branch=REL_17_STABLE" | cat - typedefs.list | sort | uniq > typedefs-full.list

# Indents projects sources.
indent:
	pgindent --typedefs=typedefs-full.list --excludes=pgindent_excludes .

.PHONY: update-typedefs indent
