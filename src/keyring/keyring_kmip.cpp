/*
 * KMIP based keyring provider, implemented on top of the C++ kmipclient
 * library.
 */

extern "C"
{
#include "postgres.h"

#include "keyring/keyring_api.h"
#include "keyring/keyring_kmip.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif
}

#include "kmipclient/Kmip.hpp"
#include "kmipclient/KmipClient.hpp"
#include "kmipclient/SymmetricKey.hpp"
#include "kmipcore/kmip_enums.hpp"

#include <exception>
#include <vector>

namespace
{
/* Timeout applied to connect, handshake and every read/write, in ms. */
constexpr int KMIP_TIMEOUT_MS = 10000;

/*
 * Run a kmipclient operation, translating any C++ exception it throws into
 * an ereport() at the given level. Returns true on success.
 *
 * body() must keep all kmipclient objects within its own scope: ereport()
 * runs only after body() has unwound, so a backend ERROR longjmp can never
 * skip a C++ destructor.
 */
template <typename F>
bool
kmip_run(int elevel, const char *what, F &&body)
{
	char errbuf[256];
	bool ok = true;

	try
	{
		body();
	}
	catch (const std::exception &e)
	{
		snprintf(errbuf, sizeof(errbuf), "%s", e.what());
		ok = false;
	}
	catch (...)
	{
		snprintf(errbuf, sizeof(errbuf), "unknown error");
		ok = false;
	}

	if (!ok)
		ereport(elevel, errmsg("%s: %s", what, errbuf));

	return ok;
}

kmipclient::Kmip
kmip_connect(KmipKeyring *kmip_keyring)
{
	return kmipclient::Kmip(kmip_keyring->kmip_host, kmip_keyring->kmip_port,
	                        kmip_keyring->kmip_cert_path,
	                        kmip_keyring->kmip_key_path,
	                        kmip_keyring->kmip_ca_path, KMIP_TIMEOUT_MS);
}
} /* namespace */

extern "C"
{

static void
kmip_set_key(GenericKeyring *keyring, KeyInfo *key)
{
	KmipKeyring *kmip_keyring = (KmipKeyring *)keyring;

	kmip_run(ERROR, "could not store key on KMIP server",
	         [&]
	         {
		         auto kmip = kmip_connect(kmip_keyring);
		         auto sk = kmipclient::SymmetricKey::aes_from_value(
		             std::vector<unsigned char>(
		                 key->data.data, key->data.data + key->data.len));

		         (void)kmip.client().op_register_key(key->name, "", sk);
	         });
}

static KeyInfo *
kmip_get_key(GenericKeyring *keyring, const char *key_name,
             KeyringReturnCode *return_code)
{
	KmipKeyring *kmip_keyring = (KmipKeyring *)keyring;
	unsigned char keydata[MAX_KEY_DATA_SIZE];
	int keylen = 0;
	size_t num_found = 0;
	bool connected = false;
	bool oversized = false;
	KeyInfo *key;

	*return_code = KEYRING_CODE_SUCCESS;

	if (!kmip_run(
	        WARNING, "could not retrieve key from KMIP server",
	        [&]
	        {
		        auto kmip = kmip_connect(kmip_keyring);

		        connected = true;

		        const auto ids = kmip.client().op_locate_by_name(
		            key_name,
		            kmipclient::object_type::KMIP_OBJTYPE_SYMMETRIC_KEY);

		        num_found = ids.size();
		        if (num_found != 1)
			        return;

		        const auto k = kmip.client().op_get_key(ids[0]);
		        const std::vector<unsigned char> &value = k->value();

		        if (value.size() > sizeof(keydata))
		        {
			        oversized = true;
			        return;
		        }

		        keylen = (int)value.size();
		        memcpy(keydata, value.data(), value.size());
	        }))
	{
		if (connected)
			*return_code = KEYRING_CODE_RESOURCE_NOT_AVAILABLE;
		return NULL;
	}

	if (num_found == 0)
		return NULL;

	if (num_found > 1)
	{
		ereport(
		    WARNING,
		    errmsg(
		        "KMIP server contains multiple results for key, ignoring"));
		*return_code = KEYRING_CODE_RESOURCE_NOT_AVAILABLE;
		return NULL;
	}

	if (oversized)
	{
		ereport(WARNING,
		        errmsg("keyring provider returned invalid key size"));
		*return_code = KEYRING_CODE_INVALID_KEY;
		return NULL;
	}

	key = palloc_object(KeyInfo);
	memset(key->name, 0, sizeof(key->name));
	memcpy(key->name, key_name, strnlen(key_name, sizeof(key->name) - 1));
	key->data.len = keylen;
	memcpy(key->data.data, keydata, keylen);

	return key;
}

static void
kmip_validate(GenericKeyring *keyring)
{
	KmipKeyring *kmip_keyring = (KmipKeyring *)keyring;

	kmip_run(ERROR, "could not connect to KMIP server",
	         [&] { auto kmip = kmip_connect(kmip_keyring); });
}

static const TDEKeyringRoutine keyringKmipRoutine = {
    .keyring_get_key = kmip_get_key,
    .keyring_store_key = kmip_set_key,
    .keyring_validate = kmip_validate,
};

void
InstallKmipKeyring(void)
{
	RegisterKeyProviderType(&keyringKmipRoutine, KMIP_KEY_PROVIDER);
}

} /* extern "C" */
