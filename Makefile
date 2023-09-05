# contrib/pg_tde/Makefile

PGFILEDESC = "pg_tde access method"
MODULE_big = pg_tde
EXTENSION = pg_tde
DATA = pg_tde--1.0.sql
REGRESS = pg_tde
TAP_TESTS = 0

OBJS = src/encryption/enc_tuple.o \
src/encryption/enc_aes.o \
src/access/heapam_visibility.o \
src/access/heapam_handler.o \
src/access/heapam.o \
src/access/heaptoast.o \
src/access/hio.o \
src/access/pruneheap.o \
src/access/rewriteheap.o \
src/access/vacuumlazy.o \
src/access/visibilitymap.o \
src/access/pg_tde_tdemap.o \
src/transam/pg_tde_xact_handler.o \
src/keyring/keyring_config.o \
src/keyring/keyring_file.o \
src/keyring/keyring_api.o \
src/pg_tde.o


ifdef USE_PGXS
PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
override PG_CPPFLAGS += -I$(CURDIR)/src/include
# TODO: use proper configure for this
override PG_CPPFLAGS += -I/usr/include/json-c
include $(PGXS)
else
subdir = contrib/postgres-tde-ext
top_builddir = ../..
override PG_CPPFLAGS += -I$(top_srcdir)/$(subdir)/src/include
# TODO: use proper configure for this
override PG_CPPFLAGS += -I/usr/include/json-c
include $(top_builddir)/src/Makefile.global
include $(top_srcdir)/contrib/contrib-global.mk
endif

SHLIB_LINK += $(filter -lcrypto -lssl, -ljson-c $(LIBS))
