/*
 * Encrypted XLog storage manager
 */

#ifndef PG_TDE_XLOGSMGR_H
#define PG_TDE_XLOGSMGR_H

#include "postgres.h"

#include "access/pg_tde_xlog_keys.h"

extern Size TDEXLogSmgrShmemSize(void);
extern void TDEXLogSmgrShmemInit(void);
extern void TDEXLogSmgrInit(void);
extern void TDEXLogSmgrInitWrite(bool encrypt_xlog, int key_len);
extern void TDEXLogSmgrInitWriteOldKeys(void);

extern void TDEXLogCryptBuffer(const void *buf, void *out_buf, size_t count, off_t offset,
							   TimeLineID tli, XLogSegNo segno, int segSize);

extern bool tde_ensure_xlog_key_location(WalLocation loc);

/*
 * Just a helper for the code clarity. See a TODO comment for
 * TDEXLogSmgrInitWrite().
 */
static inline void
TDEXLogSmgrInitUnencryptedWrite(void)
{
	/* The key length does not matter for unencrypted writes. */
	TDEXLogSmgrInitWrite(false, KEY_DATA_SIZE_128);
}

#endif							/* PG_TDE_XLOGSMGR_H */
