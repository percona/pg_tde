/*
 * TDE redefinitions for frontend included code
 */

#ifndef PG_TDE_EREPORT_H
#define PG_TDE_EREPORT_H

#ifdef FRONTEND

#include <stdarg.h>

#include "postgres_fe.h"
#include "common/logging.h"
#include "common/file_perm.h"
#include "utils/elog.h"

#ifdef __GNUC__
#pragma GCC diagnostic ignored "-Wunused-macros"
#pragma GCC diagnostic ignored "-Wunused-value"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wextra"
#endif

/*
 * Errors handling
 * ----------------------------------------
 */

static int	tde_fe_error_level = 0;

static inline enum pg_log_level
tde_fe_log_level(void)
{
	if (tde_fe_error_level >= ERROR)
		return PG_LOG_ERROR;
	else if (tde_fe_error_level >= WARNING)
		return PG_LOG_WARNING;
	else if (tde_fe_error_level >= LOG)
		return PG_LOG_INFO;
	else
		return PG_LOG_DEBUG;
}

static inline int
tde_fe_errlog_v(enum pg_log_part part, const char *fmt, va_list ap)
{
	pg_log_generic_v(tde_fe_log_level(), part, fmt, ap);
	return 0;
}

static inline int tde_fe_errmsg(const char *fmt,...) pg_attribute_printf(1, 2);
static inline int
tde_fe_errmsg(const char *fmt,...)
{
	va_list		ap;

	va_start(ap, fmt);
	tde_fe_errlog_v(PG_LOG_PRIMARY, fmt, ap);
	va_end(ap);
	return 0;
}

static inline int tde_fe_errdetail(const char *fmt,...) pg_attribute_printf(1, 2);
static inline int
tde_fe_errdetail(const char *fmt,...)
{
	va_list		ap;

	va_start(ap, fmt);
	tde_fe_errlog_v(PG_LOG_DETAIL, fmt, ap);
	va_end(ap);
	return 0;
}

static inline int tde_fe_errhint(const char *fmt,...) pg_attribute_printf(1, 2);
static inline int
tde_fe_errhint(const char *fmt,...)
{
	va_list		ap;

	va_start(ap, fmt);
	tde_fe_errlog_v(PG_LOG_HINT, fmt, ap);
	va_end(ap);
	return 0;
}

#define errmsg(...) tde_fe_errmsg(__VA_ARGS__)
#define errdetail(...) tde_fe_errdetail(__VA_ARGS__)
#define errhint(...) tde_fe_errhint(__VA_ARGS__)

#define errcode_for_file_access() NULL
#define errcode(e) NULL

#define tde_error_handle_exit(elevel) \
	do {							\
		if (elevel >= PANIC)		\
			pg_unreachable();		\
		else if (elevel >= ERROR)	\
			exit(1);				\
	} while(0)

#undef elog
#define elog(elevel, fmt, ...) \
	do {							\
		tde_fe_error_level = elevel;	\
		errmsg(fmt, ##__VA_ARGS__);		\
		tde_error_handle_exit(elevel);	\
	} while(0)

#undef ereport
#define ereport(elevel,...)		\
	do {							\
		tde_fe_error_level = elevel;	\
		__VA_ARGS__;					\
		tde_error_handle_exit(elevel);	\
	} while(0)

#define data_sync_elevel(elevel) (elevel)

/*
 * -------------
 */

#define LWLockAcquire(lock, mode) NULL
#define LWLockRelease(lock_files) NULL
#define LWLockHeldByMeInMode(lock, mode) true
#define LWLock void
#define LWLockMode void*
#define LW_SHARED NULL
#define LW_EXCLUSIVE NULL
#define tde_lwlock_enc_keys() NULL

#define OpenTransientFile(fileName, fileFlags) open(fileName, fileFlags, PG_FILE_MODE_OWNER)
#define CloseTransientFile(fd) close(fd)
#define AllocateFile(name, mode) fopen(name, mode)
#define FreeFile(file) fclose(file)

#define pg_fsync(fd) fsync(fd)

#define pg_read_barrier() NULL

extern void pg_tde_fe_init(const char *kring_dir);

#endif							/* FRONTEND */

#endif							/* PG_TDE_EREPORT_H */
