#include "postgres.h"

#include <openssl/err.h>
#include <openssl/rand.h>

#include "encryption/enc_tde.h"
#include "encryption/enc_aes.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

#define AES_BLOCK_SIZE 		        16
#define NUM_AES_BLOCKS_IN_BATCH     200
#define DATA_BYTES_PER_AES_BATCH    (NUM_AES_BLOCKS_IN_BATCH * AES_BLOCK_SIZE)
#define TDE_BLOCK_IV_LEN            16

#ifdef ENCRYPTION_DEBUG
static void
iv_prefix_debug(const char *iv_prefix, char *out_hex)
{
	for (int i = 0; i < 16; ++i)
	{
		sprintf(out_hex + i * 2, "%02x", (int) *(iv_prefix + i));
	}
	out_hex[32] = 0;
}
#endif

uint32
pg_tde_cipher_key_length(CipherType cipher)
{
	switch (cipher)
	{
		case CIPHER_AES_128:
			return KEY_DATA_SIZE_128;
		case CIPHER_AES_256:
			return KEY_DATA_SIZE_256;

		default:
			elog(ERROR, "failed to get key size from the unknown cipher %d",
				 cipher);
	}
}

void
pg_tde_generate_internal_key(InternalKey *int_key, int key_len)
{
	Assert(key_len == 16 || key_len == 32);

	/*
	 * key_len might be less then a size of the memory allocated for the key,
	 * so zero it just in case.
	 */
	memset(&int_key->key, 0, sizeof(int_key->key));

	if (!RAND_bytes(int_key->key, key_len))
		ereport(ERROR,
				errcode(ERRCODE_INTERNAL_ERROR),
				errmsg("could not generate internal key: %s",
					   ERR_error_string(ERR_get_error(), NULL)));
	if (!RAND_bytes(int_key->base_iv, INTERNAL_KEY_IV_LEN))
		ereport(ERROR,
				errcode(ERRCODE_INTERNAL_ERROR),
				errmsg("could not generate IV: %s",
					   ERR_error_string(ERR_get_error(), NULL)));

	int_key->key_len = key_len;
}

/*
 * XOR n bytes of data with keystream into out.
 *
 * The distinct variant's restrict qualifiers let the compiler
 * auto-vectorize the XOR, but require non-overlapping buffers.
 * The plain variant is used for in-place operation (out == data).
 */
static inline void
tde_xor_stream(char *out, const char *data, const unsigned char *keystream, uint32 n)
{
	for (uint32 i = 0; i < n; i++)
		out[i] = data[i] ^ keystream[i];
}

static inline void
tde_xor_stream_distinct(char *restrict out, const char *restrict data,
						const unsigned char *restrict keystream, uint32 n)
{
	Assert(((uintptr_t) out + n <= (uintptr_t) data) || ((uintptr_t) out > (uintptr_t) data + n));
	for (uint32 i = 0; i < n; i++)
		out[i] = data[i] ^ keystream[i];
}

/*
 * Encrypts/decrypts data with a given key. The result is written to out,
 * which may alias data (in-place operation is supported).
 *
 * start_offset: is the absolute location of start of data in the file.
 */
void
pg_tde_stream_crypt(const char *iv_prefix,
					uint32 start_offset,
					const char *data,
					uint32 data_len,
					char *out,
					const uint8 *key,
					int key_len,
					void **ctxPtr)
{
	const uint64 aes_start_block = start_offset / AES_BLOCK_SIZE;
	const uint64 aes_end_block = (start_offset + data_len + (AES_BLOCK_SIZE - 1)) / AES_BLOCK_SIZE;
	const uint64 aes_block_no = start_offset % AES_BLOCK_SIZE;
	uint32		batch_no = 0;
	uint32		data_index = 0;

	/*
	 * Our callers pass either fully overlapping (out == data, in-place) or
	 * fully disjoint buffers, never partial overlap.
	 */
	const bool	in_place = (out == data);

	/* do max NUM_AES_BLOCKS_IN_BATCH blocks at a time */
	for (uint64 batch_start_block = aes_start_block; batch_start_block < aes_end_block; batch_start_block += NUM_AES_BLOCKS_IN_BATCH)
	{
		unsigned char enc_key[DATA_BYTES_PER_AES_BATCH];
		uint32		current_batch_bytes;
		uint32		key_offset;
		uint64		batch_end_block = Min(batch_start_block + NUM_AES_BLOCKS_IN_BATCH, aes_end_block);

		AesCtrEncryptedZeroBlocks(ctxPtr, key, key_len, iv_prefix, batch_start_block, batch_end_block, enc_key);

#ifdef ENCRYPTION_DEBUG
		{
			char		ivp_debug[33];

			iv_prefix_debug(iv_prefix, ivp_debug);
			ereport(LOG,
					errmsg("pg_tde_stream_crypt batch_no: %d start_offset: %lu data_len: %u, batch_start_block: %lu, batch_end_block: %lu, iv_prefix: %s",
						   batch_no, start_offset, data_len, batch_start_block, batch_end_block, ivp_debug));
		}
#endif

		current_batch_bytes = ((batch_end_block - batch_start_block) * AES_BLOCK_SIZE)
			- (batch_no > 0 ? 0 : aes_block_no);	/* first batch skips
													 * aes_block_no-th bytes
													 * of enc_key */
		if ((data_index + current_batch_bytes) > data_len)
			current_batch_bytes = data_len - data_index;

		/*
		 * The key stream is tied to the absolute file position, so byte N
		 * must use the same key stream byte regardless of start_offset.
		 * enc_key is block-aligned, so the first batch starts reading it at
		 * aes_block_no (= start_offset % AES_BLOCK_SIZE); later batches start
		 * at 0.
		 */
		key_offset = (batch_no > 0 ? 0 : aes_block_no);

		if (in_place)
			tde_xor_stream(out + data_index, data + data_index,
						   enc_key + key_offset, current_batch_bytes);
		else
			tde_xor_stream_distinct(out + data_index, data + data_index,
									enc_key + key_offset, current_batch_bytes);

		data_index += current_batch_bytes;
		batch_no++;
	}
}

/*
 * The initialization vector of a block is its block number converted to a
 * 128 bit big endian number plus the forknumber XOR the base IV of the
 * relation file.
 */
static void
CalcBlockIv(ForkNumber forknum, BlockNumber bn, const unsigned char *base_iv, unsigned char *iv)
{
	memset(iv, 0, TDE_BLOCK_IV_LEN);

	/* The init fork is copied to the main fork so we must use the same IV */
	iv[7] = forknum == INIT_FORKNUM ? MAIN_FORKNUM : forknum;

	iv[12] = bn >> 24;
	iv[13] = bn >> 16;
	iv[14] = bn >> 8;
	iv[15] = bn;

	for (int i = 0; i < TDE_BLOCK_IV_LEN; i++)
		iv[i] ^= base_iv[i];
}

void
tde_decrypt_smgr_block(InternalKey *rel_key, ForkNumber forknum, BlockNumber blocknum, const unsigned char *in, unsigned char *out)
{
	unsigned char iv[TDE_BLOCK_IV_LEN];
	bool		allZero = true;

	/*
	 * Detect unencrypted all-zero pages written by smgrzeroextend() by
	 * looking at the first 32 bytes of the page.
	 *
	 * Not encrypting all-zero pages is safe because they are only written at
	 * the end of the file when extending a table on disk so they tend to be
	 * short lived plus they only leak a slightly more accurate table size
	 * than one can glean from just the file size.
	 */
	for (int i = 0; i < 32; ++i)
	{
		if (in[i] != 0)
		{
			allZero = false;
			break;
		}
	}

	if (allZero)
		return;

	CalcBlockIv(forknum, blocknum, rel_key->base_iv, iv);

	AesDecrypt(rel_key->key, rel_key->key_len, iv, in, BLCKSZ, out);
}

void
tde_encrypt_smgr_block(InternalKey *rel_key, ForkNumber forknum, BlockNumber blocknum, const unsigned char *in, unsigned char *out)
{
	unsigned char iv[TDE_BLOCK_IV_LEN];

	CalcBlockIv(forknum, blocknum, rel_key->base_iv, iv);

	AesEncrypt(rel_key->key, rel_key->key_len, iv, in, BLCKSZ, out);
}
