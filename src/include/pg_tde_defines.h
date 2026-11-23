/*
 * Debug definitions for pg_tde
 */

#ifndef PG_TDE_DEFINES_H
#define PG_TDE_DEFINES_H

/* #define ENCRYPTION_DEBUG 1 */
/* #define KEYRING_DEBUG 1 */
/* #define TDE_XLOG_DEBUG 1 */

#if !defined(FRONTEND) && PG_VERSION_NUM >= 170000
#include "utils/injection_point.h"
#if PG_VERSION_NUM >= 180000
#define TDE_INJECTION_POINT(name) INJECTION_POINT(name, NULL)
#else
#define TDE_INJECTION_POINT(name) INJECTION_POINT(name)
#endif
#else
#define TDE_INJECTION_POINT(name) ((void) 0)
#endif

#endif							/* PG_TDE_DEFINES_H */
