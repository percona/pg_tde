/*
 * GUC variables for pg_tde
 */

#ifndef TDE_GUC_H
#define TDE_GUC_H

#include "c.h"

extern bool AllowInheritGlobalProviders;
extern bool EncryptXLog;
extern bool EnforceEncryption;
extern int	Cipher;
extern int	TdeKeyLength;

typedef enum CipherOption
{
	TDE_CIPHER_AES_128,
	TDE_CIPHER_AES_256,
}			CipherOption;

extern void TdeGucInit(void);

#endif							/* TDE_GUC_H */
