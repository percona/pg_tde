#include "pg_tde_defines.h"

#include "postgres.h"
#include "utils/memutils.h"

#include "access/pg_tde_tdemap.h"
#include "encryption/enc_tuple.h"
#include "encryption/enc_aes.h"
#include "storage/bufmgr.h"
#include "keyring/keyring_api.h"

#define AES_BLOCK_SIZE 16

#ifdef ENCRYPTION_DEBUG
	/* While in active development, We are emmiting a LOG message for debug data when ENCRYPTION_DEBUG is enabled.*/
	const int enc_log_elevel = LOG;
#else
	const int enc_log_elevel = DEBUG2;
#endif


/* ================================================================
 * ACTUAL ENCRYPTION/DECRYPTION FUNCTIONS
 * ================================================================
 *
 * data and out have to be different addresses without overlap!
 * start_offset: is the absolute location of start of data in the file
 * The only difference between enc and dec is how we calculate offsetInPage
 */

void
pg_tde_crypt(uint64 start_offset, const char* data, uint32 data_len, char* out, RelKeysData* keys, const char* context)
{
    uint64 aes_start_block = start_offset / AES_BLOCK_SIZE;
    uint64 aes_end_block = (start_offset + data_len + (AES_BLOCK_SIZE -1)) / AES_BLOCK_SIZE;
    uint64 aes_block_no = start_offset % AES_BLOCK_SIZE;
    unsigned char* encKey;

    encKey = palloc(AES_BLOCK_SIZE * (aes_end_block - aes_start_block + 1));

    // TODO: verify key length!
    Aes128EncryptedZeroBlocks2(&(keys->internal_key[0].ctx), keys->internal_key[0].key, aes_start_block, aes_end_block, encKey);

    ereport(enc_log_elevel,
        (errmsg("%s: Start offset: %lu Data_Len: %u, AesBlock: %lu, BlockOffset: %lu",
				context?context:"", start_offset, data_len, aes_start_block, aes_block_no)));

    for(unsigned i = 0; i < data_len; ++i)
    {
#if ENCRYPTION_DEBUG > 1
        fprintf(stderr, " >> 0x%02hhX 0x%02hhX\n", v & 0xFF, (v ^ encKey[aes_block_no + i]) & 0xFF);
#endif
        out[i] = data[i] ^ encKey[aes_block_no + i];
    }
    pfree(encKey);
}

/*
 * pg_tde_move_encrypted_data:
 * decrypts and encrypts data in one go
*/
void
pg_tde_move_encrypted_data(uint64 read_start_offset, const char* read_data,
				uint64 write_start_offset, char* write_data,
				uint32 data_len, RelKeysData* keys, const char* context)
{
    uint64 read_aes_start_block = read_start_offset / AES_BLOCK_SIZE;
    uint64 read_aes_end_block = (read_start_offset + data_len + (AES_BLOCK_SIZE -1)) / AES_BLOCK_SIZE;
    uint64 read_aes_block_no = read_start_offset % AES_BLOCK_SIZE;
    unsigned char* read_encKey;

    uint64 write_aes_start_block = write_start_offset / AES_BLOCK_SIZE;
    uint64 write_aes_end_block = (write_start_offset + data_len + (AES_BLOCK_SIZE -1)) / AES_BLOCK_SIZE;
    uint64 write_aes_block_no = write_start_offset % AES_BLOCK_SIZE;
    unsigned char* write_encKey;

    read_encKey = palloc(AES_BLOCK_SIZE * (read_aes_end_block - read_aes_start_block + 1));
    write_encKey = palloc(AES_BLOCK_SIZE * (write_aes_end_block - write_aes_start_block + 1));

    // TODO: verify key length!
    Aes128EncryptedZeroBlocks2(&(keys->internal_key[0].ctx), keys->internal_key[0].key, read_aes_start_block, read_aes_end_block, read_encKey);
    Aes128EncryptedZeroBlocks2(&(keys->internal_key[0].ctx), keys->internal_key[0].key, write_aes_start_block, write_aes_end_block, write_encKey);

    ereport(enc_log_elevel,
        (errmsg("%s: start read_offset: %lu, read_AesBlock: %lu, read_BlockOffset: %lu, start write_offset: %lu, write_AesBlock: %lu, write_BlockOffset: %lu Data_Len: %u",
				context?context:"", read_start_offset,  read_aes_start_block, read_aes_block_no, write_start_offset,  write_aes_start_block, write_aes_block_no, data_len)));

    for(unsigned i = 0; i < data_len; ++i)
    {
		char decrypted_byte;
#if ENCRYPTION_DEBUG > 1
        fprintf(stderr, " >> 0x%02hhX 0x%02hhX\n", v & 0xFF, (v ^ encKey[aes_block_no + i]) & 0xFF);
#endif
        decrypted_byte = read_data[i] ^ read_encKey[read_aes_block_no + i];

        write_data[i] = decrypted_byte ^ write_encKey[write_aes_block_no + i];
    }
    pfree(read_encKey);
    pfree(write_encKey);
}

/*
 * pg_tde_crypt_tuple:
 * Does the encryption/decryption of tuple data in place
 * page: Page containing the tuple, Used to calculate the offset of tuple in the page
 * tuple: HeapTuple to be encrypted/decrypted
 * out_tuple: to encrypt/decrypt into. If you want to do inplace encryption/decryption, pass tuple as out_tuple
 * context: Optional context message to be used in debug log
 * */
void
pg_tde_crypt_tuple(BlockNumber bn, Page page, HeapTuple tuple, HeapTuple out_tuple, RelKeysData* keys, const char* context)
{
    uint32 data_len = tuple->t_len - tuple->t_data->t_hoff;
    uint64 tuple_offset_in_page = (char*)tuple->t_data - (char*)page;
    uint64 tuple_offset_in_file = (bn * BLCKSZ) + tuple_offset_in_page;
    char *tup_data = (char*)tuple->t_data + tuple->t_data->t_hoff;
    char *out_data = (char*)out_tuple->t_data + out_tuple->t_data->t_hoff;

    ereport(enc_log_elevel,
        (errmsg("%s: table Oid: %u block no: %u data size: %u, tuple offset in file: %lu",
                context?context:"", tuple->t_tableOid, bn,
                data_len, tuple_offset_in_file)));

    pg_tde_crypt(tuple_offset_in_file, tup_data, data_len, out_data, keys, context);
}


// ================================================================
// HELPER FUNCTIONS FOR ENCRYPTION
// ================================================================

OffsetNumber
PGTdePageAddItemExtended(RelFileLocator rel,
					Oid oid,
					BlockNumber bn, 
					Page page,
					Item item,
					Size size,
					OffsetNumber offsetNumber,
					int flags)
{
	OffsetNumber off = PageAddItemExtended(page,item,size,offsetNumber,flags);
	PageHeader	phdr = (PageHeader) page;
	unsigned long header_size = ((HeapTupleHeader)item)->t_hoff;

	char* toAddr = ((char*)phdr) + phdr->pd_upper + header_size;
	char* data = item + header_size;
	uint64 offset_in_page = ((char*)phdr) + phdr->pd_upper - (char*)page;
	uint32	data_len = size - header_size;

	RelKeysData *keys = GetRelationKeys(rel);

	PG_TDE_ENCRYPT_PAGE_ITEM(bn, offset_in_page, data, data_len, toAddr, keys);

	return off;
}

TupleTableSlot *
PGTdeExecStoreBufferHeapTuple(Relation rel, HeapTuple tuple, TupleTableSlot *slot, Buffer buffer)
{
	HeapTuple* tuple_ptr = &tuple;

    if (rel->rd_rel->relkind != RELKIND_TOASTVALUE)
    {
		MemoryContext oldContext;
        Page pageHeader;
		HeapTuple	decrypted_tuple;
        RelKeysData *keys = GetRelationKeys(rel->rd_locator);
        pageHeader = BufferGetPage(buffer);

		oldContext = MemoryContextSwitchTo(slot->tts_mcxt);
		decrypted_tuple = heap_copytuple(tuple);
		MemoryContextSwitchTo(oldContext);

		PG_TDE_DECRYPT_TUPLE_EX(BufferGetBlockNumber(buffer), pageHeader, tuple, decrypted_tuple, keys, "ExecStoreBuffer");
		tuple_ptr = &decrypted_tuple;

    }
	return  ExecStoreBufferHeapTuple(*tuple_ptr, slot, buffer);
}

TupleTableSlot *
PGTdeExecStorePinnedBufferHeapTuple(Relation rel, HeapTuple tuple, TupleTableSlot *slot, Buffer buffer)
{
	HeapTuple* tuple_ptr = &tuple;

    if (rel->rd_rel->relkind != RELKIND_TOASTVALUE)
    {
		MemoryContext oldContext;
        Page pageHeader;
		HeapTuple	decrypted_tuple;
        RelKeysData *keys = GetRelationKeys(rel->rd_locator);
        pageHeader = BufferGetPage(buffer);

		oldContext = MemoryContextSwitchTo(slot->tts_mcxt);
		decrypted_tuple = heap_copytuple(tuple);
		MemoryContextSwitchTo(oldContext);

		PG_TDE_DECRYPT_TUPLE_EX(BufferGetBlockNumber(buffer), pageHeader, tuple, decrypted_tuple, keys, "ExecStoreBuffer");
		tuple_ptr = &decrypted_tuple;
    }
	return  ExecStorePinnedBufferHeapTuple(*tuple_ptr, slot, buffer);
}
