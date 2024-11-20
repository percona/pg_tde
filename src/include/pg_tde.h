/*-------------------------------------------------------------------------
 *
 * pg_tde.h
 * src/include/pg_tde.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef PG_TDE_H
#define PG_TDE_H

#define PG_TDE_DATA_DIR	"pg_tde"

typedef struct XLogExtensionInstall
{
	Oid	database_id;
} XLogExtensionInstall;

typedef void (*pg_tde_on_ext_install_callback) (int tde_tbl_count, XLogExtensionInstall *ext_info, bool redo, void *arg);

extern void on_ext_install(pg_tde_on_ext_install_callback function, void *arg);

extern void extension_install_redo(XLogExtensionInstall *xlrec);

extern void pg_tde_init_data_dir(void);
#endif	/* PG_TDE_H */
