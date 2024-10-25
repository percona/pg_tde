/*-------------------------------------------------------------------------
 *
 * tdeheap_slot.h
 *	  TupleSlot implementation for TDE
 *
 * src/include/access/pg_tde_slot.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef PG_TDE_SLOT_H
#define PG_TDE_SLOT_H


#include "postgres.h"
#include "executor/tuptable.h"
#include "access/pg_tde_tdemap.h"
#include "utils/relcache.h"

/* 
 * Number of buffers in ExecStorePinnedBuffer to hold decrypted tuple data.
 *
 * We hold tuple's decrypted t_data in a preallocated buffer in TTS. This allows
 * us to save a lot of memory and palloc calls during sequential scans etc. But
 * Merge Join and Hosh Join reuse the same TTS for the inner and outer tuple and
 * may compare them. In that case, both tuples would point to the same data. To
 * avoid this we have a number of decryption buffers and keep circling. So inner
 * and outer tuples would point to different data.
 */
#define TDE_TTS_DECRYPTED_BUFFS 2

/* heap tuple residing in a buffer */
typedef struct TDEBufferHeapTupleTableSlot
{
	pg_node_attr(abstract)

	HeapTupleTableSlot base;

	/*
	 * If buffer is not InvalidBuffer, then the slot is holding a pin on the
	 * indicated buffer page; drop the pin when we release the slot's
	 * reference to that buffer.  (TTS_FLAG_SHOULDFREE should not be set in
	 * such a case, since presumably base.tuple is pointing into the buffer.)
	 */
	Buffer		buffer;			/* tuple's buffer, or InvalidBuffer */
	char		decrypted_buffer[TDE_TTS_DECRYPTED_BUFFS][BLCKSZ];
	uint8		current_buff;
	RelKeyData *cached_relation_key;
} TDEBufferHeapTupleTableSlot;

static inline char*
TDESlotGetDecryptedBuffer(TDEBufferHeapTupleTableSlot *bslot)
{
	char *buf = bslot->decrypted_buffer[bslot->current_buff++];

	if (bslot->current_buff == TDE_TTS_DECRYPTED_BUFFS)
		bslot->current_buff = 0;

	return buf;
}

extern PGDLLIMPORT const TupleTableSlotOps TTSOpsTDEBufferHeapTuple;

#define TTS_IS_TDE_BUFFERTUPLE(slot) ((slot)->tts_ops == &TTSOpsTDEBufferHeapTuple)

extern TupleTableSlot *PGTdeExecStorePinnedBufferHeapTuple(Relation rel,
						HeapTuple tuple,
						TupleTableSlot *slot,
						Buffer buffer);
extern TupleTableSlot *PGTdeExecStoreBufferHeapTuple(Relation rel,
                         HeapTuple tuple,
						 TupleTableSlot *slot,
						 Buffer buffer);

#endif /* PG_TDE_SLOT_H */