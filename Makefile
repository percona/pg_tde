# contrib/pg_tde/Makefile

PGFILEDESC = "pg_tde access method"
MODULE_big = pg_tde
EXTENSION = pg_tde
DATA = pg_tde--1.0-beta2.sql

REGRESS_OPTS = --temp-config $(top_srcdir)/contrib/pg_tde/pg_tde.conf
REGRESS = toast_decrypt_basic \
toast_extended_storage_basic \
move_large_tuples_basic \
non_sorted_off_compact_basic \
update_compare_indexes_basic \
pg_tde_is_encrypted_basic \
test_issue_153_fix_basic \
multi_insert_basic \
update_basic \
subtransaction_basic \
trigger_on_view_basic \
change_access_method_basic \
insert_update_delete_basic \
keyprovider_dependency_basic \
vault_v2_test_basic \
alter_index_basic \
merge_join_basic \
tablespace_basic
TAP_TESTS = 1

OBJS = src/encryption/enc_tde.o \
src/encryption/enc_aes.o \
src/access/pg_tde_slot.o \
src/access/pg_tde_tdemap.o \
src$(MAJORVERSION)/access/pg_tde_io.o \
src$(MAJORVERSION)/access/pg_tdeam_visibility.o \
src$(MAJORVERSION)/access/pg_tdeam.o \
src$(MAJORVERSION)/access/pg_tdetoast.o \
src$(MAJORVERSION)/access/pg_tde_prune.o \
src$(MAJORVERSION)/access/pg_tde_vacuumlazy.o \
src$(MAJORVERSION)/access/pg_tde_visibilitymap.o \
src$(MAJORVERSION)/access/pg_tde_rewrite.o \
src$(MAJORVERSION)/access/pg_tdeam_handler.o \
src/access/pg_tde_ddl.o \
src/access/pg_tde_xlog.o \
src/access/pg_tde_xlog_encrypt.o \
src/transam/pg_tde_xact_handler.o \
src/keyring/keyring_curl.o \
src/keyring/keyring_file.o \
src/keyring/keyring_vault.o \
src/keyring/keyring_kmip.o \
src/keyring/keyring_kmip_ereport.o \
src/keyring/keyring_api.o \
src/catalog/tde_global_space.o \
src/catalog/tde_keyring.o \
src/catalog/tde_keyring_parse_opts.o \
src/catalog/tde_principal_key.o \
src/common/pg_tde_shmem.o \
src/common/pg_tde_utils.o \
src/smgr/pg_tde_smgr.o \
src/pg_tde_defs.o \
src/pg_tde_event_capture.o \
src/pg_tde.o \
src/libkmip/libkmip/src/kmip.o \
src/libkmip/libkmip/src/kmip_bio.o \
src/libkmip/libkmip/src/kmip_locate.o \
src/libkmip/libkmip/src/kmip_memset.o

ifdef USE_PGXS
PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
override PG_CPPFLAGS += -I$(CURDIR)/src/include -I$(CURDIR)/src/libkmip/libkmip/include -I$(CURDIR)/src$(MAJORVERSION)/include
include $(PGXS)
else
subdir = contrib/pg_tde
top_builddir = ../..
override PG_CPPFLAGS += -I$(top_srcdir)/$(subdir)/src/include  -I$(top_srcdir)/$(subdir)/src/libkmip/libkmip/include -I$(top_srcdir)/$(subdir)/src$(MAJORVERSION)/include
include $(top_builddir)/src/Makefile.global
include $(top_srcdir)/contrib/contrib-global.mk
endif

override SHLIB_LINK += -lcurl -lcrypto -lssl

# Fetches typedefs list for PostgreSQL core and merges it with typedefs defined in this project.
# https://wiki.postgresql.org/wiki/Running_pgindent_on_non-core_code_or_development_code
update-typedefs:
	wget -q -O - "https://buildfarm.postgresql.org/cgi-bin/typedefs.pl?branch=REL_17_STABLE" | cat - typedefs.list | sort | uniq > typedefs-full.list

# Indents projects sources.
indent:
	pgindent --typedefs=typedefs-full.list --excludes=pgindent_excludes .

.PHONY: update-typedefs indent
