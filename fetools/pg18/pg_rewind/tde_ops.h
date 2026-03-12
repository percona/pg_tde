#ifndef PG_REWIND_TDE_FILE_H
#define PG_REWIND_TDE_FILE_H

extern void flush_current_key(void);
extern void ensure_tde_keys(const char *relpath);
extern void encrypt_block(unsigned char *buf, off_t file_offset);

extern void create_tde_tmp_dir(void);
extern void destroy_tde_tmp_dir(void);
extern void write_tmp_source_file(const char *fname, char *buf, size_t size);
extern void fetch_tde_dir(void);
extern void copy_tmp_tde_files(const char *from);

#endif							/* PG_REWIND_TDE_FILE_H */
