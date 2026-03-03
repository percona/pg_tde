#include "postgres.h"

#include <openssl/err.h>
#include <openssl/evp.h>

#include "encryption/enc_aes.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

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

static const EVP_CIPHER *cipher_cbc_128 = NULL;
static const EVP_CIPHER *cipher_gcm_128 = NULL;
static const EVP_CIPHER *cipher_ctr_ecb_128 = NULL;

static const EVP_CIPHER *cipher_cbc_256 = NULL;
static const EVP_CIPHER *cipher_gcm_256 = NULL;
static const EVP_CIPHER *cipher_ctr_ecb_256 = NULL;

void
AesInit(void)
{
	OPENSSL_init_crypto(OPENSSL_INIT_ADD_ALL_CIPHERS | OPENSSL_INIT_LOAD_CRYPTO_STRINGS, NULL);

	cipher_cbc_128 = EVP_aes_128_cbc();
	cipher_gcm_128 = EVP_aes_128_gcm();
	cipher_ctr_ecb_128 = EVP_aes_128_ecb();

	cipher_cbc_256 = EVP_aes_256_cbc();
	cipher_gcm_256 = EVP_aes_256_gcm();
	cipher_ctr_ecb_256 = EVP_aes_256_ecb();
}

static void
AesEcbEncrypt(EVP_CIPHER_CTX **ctxPtr, const unsigned char *key, int key_len, const unsigned char *in, int in_len, unsigned char *out)
{
	int			out_len;
	const EVP_CIPHER *cipher;

	Assert(key_len == 16 || key_len == 32);
	cipher = key_len == 32 ? cipher_ctr_ecb_256 : cipher_ctr_ecb_128;

	/*
	 * TODO: Currently, only Ecb (WAL) use cached context. This caching was
	 * done for optimisation. Do we need it anymore?
	 */
	if (*ctxPtr == NULL)
	{
		Assert(cipher != NULL);

		*ctxPtr = EVP_CIPHER_CTX_new();

		if (EVP_CipherInit_ex(*ctxPtr, cipher, NULL, key, NULL, 1) == 0)
			ereport(ERROR,
					errmsg("EVP_CipherInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

		EVP_CIPHER_CTX_set_padding(*ctxPtr, 0);
	}
	else
		Assert(EVP_CIPHER_CTX_key_length(*ctxPtr) == key_len);

	if (EVP_CipherUpdate(*ctxPtr, out, &out_len, in, in_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	Assert(out_len == in_len);
}

static void
AesRunCbc(int enc, const unsigned char *key, int key_len, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out)
{
	int			out_len;
	int			out_len_final;
	EVP_CIPHER_CTX *ctx = NULL;
	const EVP_CIPHER *cipher;

	Assert(key_len == 16 || key_len == 32);
	cipher = key_len == 32 ? cipher_cbc_256 : cipher_cbc_128;

	Assert(cipher != NULL);
	Assert(in_len % EVP_CIPHER_block_size(cipher) == 0);

	ctx = EVP_CIPHER_CTX_new();

	if (EVP_CipherInit_ex(ctx, cipher, NULL, key, iv, enc) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	EVP_CIPHER_CTX_set_padding(ctx, 0);

	if (EVP_CipherUpdate(ctx, out, &out_len, in, in_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CipherFinal_ex(ctx, out + out_len, &out_len_final) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherFinal_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	/*
	 * We encrypt one block (16 bytes) Our expectation is that the result
	 * should also be 16 bytes, without any additional padding
	 */
	out_len += out_len_final;
	Assert(in_len == out_len);

	EVP_CIPHER_CTX_free(ctx);
}

void
AesEncrypt(const unsigned char *key, int key_len, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out)
{
	AesRunCbc(1, key, key_len, iv, in, in_len, out);
}

void
AesDecrypt(const unsigned char *key, int key_len, const unsigned char *iv, const unsigned char *in, int in_len, unsigned char *out)
{
	AesRunCbc(0, key, key_len, iv, in, in_len, out);
}

void
AesGcmEncrypt(const unsigned char *key, int key_len, const unsigned char *iv, int iv_len, const unsigned char *aad, int aad_len, const unsigned char *in, int in_len, unsigned char *out, unsigned char *tag, int tag_len)
{
	int			out_len;
	int			out_len_final;
	EVP_CIPHER_CTX *ctx;
	const EVP_CIPHER *cipher;

	Assert(key_len == 16 || key_len == 32);
	cipher = key_len == 32 ? cipher_gcm_256 : cipher_gcm_128;

	Assert(cipher != NULL);
	Assert(in_len % EVP_CIPHER_block_size(cipher) == 0);

	ctx = EVP_CIPHER_CTX_new();

	if (EVP_EncryptInit_ex(ctx, cipher, NULL, NULL, NULL) == 0)
		ereport(ERROR,
				errmsg("EVP_EncryptInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_set_padding(ctx, 0) == 0)
		ereport(ERROR,
				errmsg("EVP_CIPHER_CTX_set_padding failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, iv_len, NULL) == 0)
		ereport(ERROR,
				errmsg("EVP_CTRL_GCM_SET_IVLEN failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) == 0)
		ereport(ERROR,
				errmsg("EVP_EncryptInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_EncryptUpdate(ctx, NULL, &out_len, (unsigned char *) aad, aad_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_EncryptUpdate(ctx, out, &out_len, in, in_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_EncryptFinal_ex(ctx, out + out_len, &out_len_final) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherFinal_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, tag_len, tag) == 0)
		ereport(ERROR,
				errmsg("EVP_CTRL_GCM_GET_TAG failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	/*
	 * We encrypt one block (16 bytes) Our expectation is that the result
	 * should also be 16 bytes, without any additional padding
	 */
	out_len += out_len_final;
	Assert(in_len == out_len);

	EVP_CIPHER_CTX_free(ctx);
}

bool
AesGcmDecrypt(const unsigned char *key, int key_len, const unsigned char *iv, int iv_len, const unsigned char *aad, int aad_len, const unsigned char *in, int in_len, unsigned char *out, unsigned char *tag, int tag_len)
{
	int			out_len;
	int			out_len_final;
	EVP_CIPHER_CTX *ctx;
	const EVP_CIPHER *cipher;

	Assert(key_len == 16 || key_len == 32);
	cipher = key_len == 32 ? cipher_gcm_256 : cipher_gcm_128;

	Assert(in_len % EVP_CIPHER_block_size(cipher) == 0);

	ctx = EVP_CIPHER_CTX_new();

	if (EVP_DecryptInit_ex(ctx, cipher, NULL, NULL, NULL) == 0)
		ereport(ERROR,
				errmsg("EVP_EncryptInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_set_padding(ctx, 0) == 0)
		ereport(ERROR,
				errmsg("EVP_CIPHER_CTX_set_padding failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, iv_len, NULL) == 0)
		ereport(ERROR,
				errmsg("EVP_CTRL_GCM_SET_IVLEN failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) == 0)
		ereport(ERROR,
				errmsg("EVP_EncryptInit_ex failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, tag_len, tag) == 0)
		ereport(ERROR,
				errmsg("EVP_CTRL_GCM_SET_TAG failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_DecryptUpdate(ctx, NULL, &out_len, aad, aad_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_DecryptUpdate(ctx, out, &out_len, in, in_len) == 0)
		ereport(ERROR,
				errmsg("EVP_CipherUpdate failed. OpenSSL error: %s", ERR_error_string(ERR_get_error(), NULL)));

	if (EVP_DecryptFinal_ex(ctx, out + out_len, &out_len_final) == 0)
	{
		EVP_CIPHER_CTX_free(ctx);
		return false;
	}

	/*
	 * We encrypt one block (16 bytes) Our expectation is that the result
	 * should also be 16 bytes, without any additional padding
	 */
	out_len += out_len_final;
	Assert(in_len == out_len);

	EVP_CIPHER_CTX_free(ctx);

	return true;
}

/*
 * This function assumes that the out buffer is big enough: at least (blockNumber2 - blockNumber1) * 16 bytes
 */
void
AesCtrEncryptedZeroBlocks(void *ctxPtr, const unsigned char *key, int key_len, const char *iv_prefix, uint64_t blockNumber1, uint64_t blockNumber2, unsigned char *out)
{
	unsigned char *p;

	Assert(blockNumber2 >= blockNumber1);

	p = out;

	for (int32 j = blockNumber1; j < blockNumber2; ++j)
	{
		/*
		 * We have 16 bytes, and a 4 byte counter. The counter is the last 4
		 * bytes. Technically, this isn't correct: the byte order of the
		 * counter depends on the endianness of the CPU running it. As this is
		 * a generic limitation of Postgres, it's fine.
		 */
		memcpy(p, iv_prefix, 16 - sizeof(j));
		p += 16 - sizeof(j);
		memcpy(p, (char *) &j, sizeof(j));
		p += sizeof(j);
	}

	AesEcbEncrypt(ctxPtr, key, key_len, out, p - out, out);
}
