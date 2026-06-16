#ifndef PG_REWIND_TDE_FILE_H
#define PG_REWIND_TDE_FILE_H

#include "common/relpath.h"

extern void ensure_tde_wal_seg(const char *relpath);
extern void ensure_tde_keys_for_rel(const char *relpath);
extern void tde_reencrypt_block_in_current_file(unsigned char *buf, off_t file_offset, ForkNumber fork);

extern void destroy_tde_tmp_dir(void);
extern void write_tmp_source_file(const char *fname, char *buf, size_t size);
extern void fetch_tde_dir(void);
extern void copy_tmp_tde_files(const char *from);
extern void init_tde(void);
extern void flush_rel_keys(void);
extern void tde_flushkey_init(void);

#endif							/* PG_REWIND_TDE_FILE_H */
