#ifndef PG_TDE_H
#define PG_TDE_H

#define PG_TDE_NAME "pg_tde"
#define PG_TDE_VERSION "2.1.0"
#define PG_TDE_VERSION_STRING PG_TDE_NAME " " PG_TDE_VERSION

#define PG_TDE_DATA_DIR	"pg_tde"

#define TDE_TRANCHE_NAME "pg_tde_tranche"

/*
 * Only numeric version (the most left byte) should be changed when updating
 * file format. Otherwise, it will break the migration process.
 */
#define PG_TDE_WAL_KEY_FILE_MAGIC 0x024B4557	/* version ID value = WEK 02 */
#define PG_TDE_SMGR_FILE_MAGIC		  0x04454454	/* version ID value = TDE
													 * 04 */

#define FILEMAGIC_VERSION(FM) ((FM & 0xF000000) >> 24)
#define FILEMAGIC_TYPE(FM) ((FM & 0x0FFFFFF))

typedef enum
{
	TDE_LWLOCK_ENC_KEY,
	TDE_LWLOCK_PI_FILES,

	/* Must be the last entry in the enum */
	TDE_LWLOCK_COUNT
}			TDELockTypes;

typedef struct XLogExtensionInstall
{
	Oid			database_id;
} XLogExtensionInstall;

extern void extension_install_redo(XLogExtensionInstall *xlrec);

#endif							/* PG_TDE_H */
