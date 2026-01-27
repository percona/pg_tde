/*
 * Encryption / Decryption of functions for TDE
 */

#ifndef ENC_TDE_H
#define ENC_TDE_H

#define TDE_KEY_NAME_LEN 256
#define KEY_DATA_SIZE_128 16	/* 128 bit encryption */
#define KEY_DATA_SIZE_256 32	/* 256 bit encryption */
#define MAX_KEY_DATA_SIZE KEY_DATA_SIZE_256 /* maximum 256 bit encryption */

typedef enum CipherType
{
	CIPHER_AES_128,
	CIPHER_AES_256,
} CipherType;

extern uint32 pg_tde_cipher_key_length(CipherType cipher);

#define INTERNAL_KEY_MAX_LEN 32 /* Max size of an Internal Key */
#define INTERNAL_KEY_IV_LEN 16

typedef struct InternalKey
{
	uint32		key_len;
	uint8		base_iv[INTERNAL_KEY_IV_LEN];
	uint8		key[INTERNAL_KEY_MAX_LEN];
} InternalKey;

extern void pg_tde_generate_internal_key(InternalKey *int_key, int key_len);
extern void pg_tde_stream_crypt(const char *iv_prefix,
								uint32 start_offset,
								const char *data,
								uint32 data_len,
								char *out,
								const uint8 *key,
								int key_len,
								void **ctxPtr);

#endif							/* ENC_TDE_H */
