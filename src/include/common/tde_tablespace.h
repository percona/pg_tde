/* src/include/common/tde_tablespace.h */
#ifndef PG_TDE_TABLESPACE_H
#define PG_TDE_TABLESPACE_H

#include "postgres.h"

#define MAX_ENCRYPTED_TABLESPACES 128

extern bool tablespace_is_encrypted(Oid spcOid);

/* Hooks called from pg_tde's shmem-size / startup plumbing. */
extern Size pg_tde_tablespace_shmem_size(void);
extern void pg_tde_tablespace_shmem_init(void);

/* WAL redo for mark/unmark records (from pg_tde's rmgr dispatch). */
extern void pg_tde_tablespace_marker_redo(Oid spcOid, bool want_encrypted);

/* DROP TABLESPACE pre-hook: emits decrypt WAL + cleans list file. */
extern void pg_tde_tablespace_drop_hook(Oid spcOid);

#endif
