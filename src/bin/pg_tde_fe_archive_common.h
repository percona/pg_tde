#ifndef PG_TDE_FE_ARCHIVE_COMMON_H
#define PG_TDE_FE_ARCHIVE_COMMON_H

#include "pg_tde.h"

/*
 * Init WAL keys. We expect pg_tde (if any) one level up from the destination
 * file dir. Hence we expect destination files in the <pgdata>/pg_wal dir and
 * keys in <pgdata>/pg_tde. No `sep` means no dir in `segpath`, hence our
 * workdir is `pg_wal` itself, therefore look at ../pg_tde.
 */
static inline void
derive_tde_dir_from_segment_path(const char *segpath, const char *sep,
								 char *tdedir, size_t tdedir_sz)
{
	if (sep != NULL)
	{
		char		segdir[MAXPGPATH];

		strlcpy(segdir, segpath, sep - segpath + 1);
		snprintf(tdedir, tdedir_sz, "%s/../" PG_TDE_DATA_DIR, segdir);
	}
	else
	{
		strlcpy(tdedir, "../" PG_TDE_DATA_DIR, tdedir_sz);
	}
}

#endif							/* PG_TDE_FE_ARCHIVE_COMMON_H */
