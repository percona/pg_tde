
#ifndef FRONTEND
#include "postgres.h"
#else
#include <assert.h>
#define Assert(p) assert(p)
#endif

#include "encryption/enc_aes.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>

#include <openssl/ssl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/err.h>

/* Implementation notes
 * =====================
 *
 * AES-CTR in a nutshell:
 * * Uses a counter, 0 for the first block, 1 for the next block, ...
 * * Encrypts the counter using AES-ECB
 * * XORs the data to the encrypted counter
 *
 * In our implementation, we want random access into any 16 byte part of the encrypted datafile.
 * This is doable with OpenSSL and directly using AES-CTR, by passing the offset in the correct format as IV.
 * Unfortunately this requires reinitializing the OpenSSL context for every seek, and that's a costly operation.
 * Initialization and then decryption of 8192 bytes takes just double the time of initialization and deecryption
 * of 16 bytes.
 *
 * To mitigate this, we reimplement AES-CTR using AES-ECB:
 * * We only initialize one ECB context per encryption key (e.g. table), and store this context
 * * When a new block is requested, we use this stored context to encrypt the position information
 * * And then XOR it with the data
 *
 * This is still not as fast as using 8k blocks, but already 2 orders of magnitude better than direct CTR with
 * 16 byte blocks.
 */


const EVP_CIPHER *cipher = NULL;
const EVP_CIPHER *cipher2 = NULL;
int	cipher_block_size = 0;

void
AesInit(void)
{
	static int initialized = 0;

	if (!initialized)
	{
		OpenSSL_add_all_algorithms();
		ERR_load_crypto_strings();

		cipher = EVP_aes_128_cbc();
		cipher_block_size = EVP_CIPHER_block_size(cipher);
		//== buffer size
			cipher2 = EVP_aes_128_ecb();

		initialized = 1;
	}
}

/*  TODO: a few things could be optimized in this. It's good enough for a prototype. */
static void
AesRunCtr(EVP_CIPHER_CTX **ctxPtr, int enc, const unsigned char *key, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out, int *out_len)
{
	if (*ctxPtr == NULL)
	{
		*ctxPtr = EVP_CIPHER_CTX_new();
		EVP_CIPHER_CTX_init(*ctxPtr);

		if (EVP_CipherInit_ex(*ctxPtr, cipher2, NULL, key, iv, enc) == 0)
		{
#ifdef FRONTEND
			fprintf(stderr, "ERROR: EVP_CipherInit_ex failed. OpenSSL error: %s\n", ERR_error_string(ERR_get_error(), NULL));
#else
			ereport(ERROR,
					(errmsg("EVP_CipherInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL))));
#endif

			return;
		}

		EVP_CIPHER_CTX_set_padding(*ctxPtr, 0);
	}

	if (EVP_CipherUpdate(*ctxPtr, out, out_len, in, in_len) == 0)
	{
#ifdef FRONTEND
		fprintf(stderr, "ERROR: EVP_CipherUpdate failed. OpenSSL error: %s\n", ERR_error_string(ERR_get_error(), NULL));
#else
		ereport(ERROR,
				(errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL))));
#endif
		return;
	}
}

static void
AesRunCbc(int enc, const unsigned char *key, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out, int *out_len)
{
	int	out_len_final = 0;
	EVP_CIPHER_CTX *ctx = NULL;

	ctx = EVP_CIPHER_CTX_new();
	EVP_CIPHER_CTX_init(ctx);

	if (EVP_CipherInit_ex(ctx, cipher, NULL, key, iv, enc) == 0)
	{
#ifdef FRONTEND
		fprintf(stderr, "ERROR: EVP_CipherInit_ex failed. OpenSSL error: %s\n", ERR_error_string(ERR_get_error(), NULL));
#else
		ereport(ERROR,
				(errmsg("EVP_CipherInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL))));
#endif
		goto cleanup;
	}

	EVP_CIPHER_CTX_set_padding(ctx, 0);
	Assert(in_len % cipher_block_size == 0);

	if (EVP_CipherUpdate(ctx, out, out_len, in, in_len) == 0)
	{
#ifdef FRONTEND
		fprintf(stderr, "ERROR: EVP_CipherUpdate failed. OpenSSL error: %s\n", ERR_error_string(ERR_get_error(), NULL));
#else
		ereport(ERROR,
				(errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL))));
#endif
		goto cleanup;
	}

	if (EVP_CipherFinal_ex(ctx, out + *out_len, &out_len_final) == 0)
	{
#ifdef FRONTEND
		fprintf(stderr, "ERROR: EVP_CipherFinal_ex failed. OpenSSL error: %s\n", ERR_error_string(ERR_get_error(), NULL));
#else
		ereport(ERROR,
				(errmsg("EVP_CipherFinal_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL))));
#endif
		goto cleanup;
	}

	/*
	 * We encrypt one block (16 bytes) Our expectation is that the result
	 * should also be 16 bytes, without any additional padding
	 */
	*out_len += out_len_final;
	Assert(in_len == *out_len);

cleanup:
	EVP_CIPHER_CTX_cleanup(ctx);
	EVP_CIPHER_CTX_free(ctx);
}

void
AesEncrypt(const unsigned char *key, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out, int *out_len)
{
	AesRunCbc(1, key, iv, in, in_len, out, out_len);
}

void
AesDecrypt(const unsigned char *key, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out, int *out_len)
{
	AesRunCbc(0, key, iv, in, in_len, out, out_len);
}

/* This function assumes that the out buffer is big enough: at least (blockNumber2 - blockNumber1) * 16 bytes
 */
void
Aes128EncryptedZeroBlocks(void *ctxPtr, const unsigned char *key, const char *iv_prefix, uint64_t blockNumber1, uint64_t blockNumber2, unsigned char *out)
{
	const unsigned char iv[16] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

	const unsigned dataLen = (blockNumber2 - blockNumber1) * 16;
	int			outLen;

	Assert(blockNumber2 >= blockNumber1);

	for (int j = blockNumber1; j < blockNumber2; ++j)
	{
		/*
		 * We have 16 bytes, and a 4 byte counter. The counter is the last 4
		 * bytes. Technically, this isn't correct: the byte order of the
		 * counter depends on the endianness of the CPU running it. As this is
		 * a generic limitation of Postgres, it's fine.
		 */
		memcpy(out + (16 * (j - blockNumber1)), iv_prefix, 12);
		memcpy(out + (16 * (j - blockNumber1)) + 12, (char *) &j, 4);
	}

	AesRunCtr(ctxPtr, 1, key, iv, out, dataLen, out, &outLen);
	Assert(outLen == dataLen);
}
