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
	char		decrypted_buffer[BLCKSZ];
	RelKeyData *cached_relation_key;
} TDEBufferHeapTupleTableSlot;

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

#endif							/* PG_TDE_SLOT_H */
