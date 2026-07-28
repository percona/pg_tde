/*
 * Contains common curl related methods.
 */

#include "postgres.h"

#include <unistd.h>

#include "keyring/keyring_curl.h"
#include "pg_tde_defines.h"

CURL	   *keyringCurl = NULL;
static pid_t keyringCurlPid = 0;

static size_t
write_func(void *ptr, size_t size, size_t nmemb, struct CurlString *s)
{
	size_t		new_len = s->len + size * nmemb;

	s->ptr = repalloc(s->ptr, new_len + 1);
	if (s->ptr == NULL)
	{
		exit(EXIT_FAILURE);
	}
	memcpy(s->ptr + s->len, ptr, size * nmemb);
	s->ptr[new_len] = '\0';
	s->len = new_len;

	return size * nmemb;
}

bool
curlSetupSession(const char *url, const char *caFile, CurlString *outStr)
{
	/*
	 * A handle created before a fork keeps the parent's connection cache, so
	 * the socket is shared with the parent and every other child. Two
	 * processes writing to it interleave their requests on one stream. Start
	 * over whenever we notice we are in a different process.
	 *
	 * The inherited handle is abandoned rather than cleaned up: cleanup would
	 * send a TLS shutdown over the connection the parent still uses.
	 */
	if (keyringCurl == NULL || keyringCurlPid != getpid())
	{
		keyringCurl = curl_easy_init();

		if (keyringCurl == NULL)
			return false;

		keyringCurlPid = getpid();
	}
	else
	{
		curl_easy_reset(keyringCurl);
	}

	if (caFile != NULL && strlen(caFile) != 0)
	{
		if (curl_easy_setopt(keyringCurl, CURLOPT_CAINFO, caFile) != CURLE_OK)
			return false;
	}
	if (curl_easy_setopt(keyringCurl, CURLOPT_FOLLOWLOCATION, 1) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_CONNECTTIMEOUT, 3) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_TIMEOUT, 10) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_WRITEFUNCTION, write_func) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_WRITEDATA, outStr) != CURLE_OK)
		return false;
	if (curl_easy_setopt(keyringCurl, CURLOPT_URL, url) != CURLE_OK)
		return false;

	return true;
}
