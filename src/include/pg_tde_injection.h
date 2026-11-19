#ifndef PG_TDE_INJECTION_H
#define PG_TDE_INJECTION_H

/*
 * Injection points exist since PostgreSQL 17, and take an argument since 18.
 *
 * Points can sit under the key lock and are also passed in redo: a backend
 * waiting at one cannot be cancelled.
 */
#if !defined(FRONTEND) && PG_VERSION_NUM >= 180000
#include "utils/injection_point.h"
#define TDE_INJECTION_POINT(name) INJECTION_POINT(name, NULL)
#elif !defined(FRONTEND) && PG_VERSION_NUM >= 170000
#include "utils/injection_point.h"
#define TDE_INJECTION_POINT(name) INJECTION_POINT(name)
#else
#define TDE_INJECTION_POINT(name) ((void) name)
#endif

#endif							/* PG_TDE_INJECTION_H */
