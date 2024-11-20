/*-------------------------------------------------------------------------
 *
 * tdeheap_xlog.h
 *	  TDE XLog resource manager
 *
 *-------------------------------------------------------------------------
 */

#ifndef PG_TDE_XLOG_H
#define PG_TDE_XLOG_H

#ifndef FRONTEND

#include "postgres.h"
#include "access/xlog.h"
#include "access/xlog_internal.h"

/* TDE XLOG resource manager */
#define XLOG_TDE_ADD_RELATION_KEY		0x00
#define XLOG_TDE_ADD_PRINCIPAL_KEY		0x10
#define XLOG_TDE_EXTENSION_INSTALL_KEY	0x20
#define XLOG_TDE_ROTATE_KEY				0x30
#define XLOG_TDE_ADD_KEY_PROVIDER_KEY 	0x40
#define XLOG_TDE_FREE_MAP_ENTRY		 	0x50

/* ID 140 is registered for Percona TDE extension: https://wiki.postgresql.org/wiki/CustomWALResourceManagers */
#define RM_TDERMGR_ID	140
#define RM_TDERMGR_NAME	"test_tdeheap_custom_rmgr"

extern void tdeheap_rmgr_redo(XLogReaderState *record);
extern void tdeheap_rmgr_desc(StringInfo buf, XLogReaderState *record);
extern const char *tdeheap_rmgr_identify(uint8 info);

static const RmgrData tdeheap_rmgr = {
	.rm_name = RM_TDERMGR_NAME,
	.rm_redo = tdeheap_rmgr_redo,
	.rm_desc = tdeheap_rmgr_desc,
	.rm_identify = tdeheap_rmgr_identify
};

#endif /* !FRONTEND */
#endif /* PG_TDE_XLOG_H */
