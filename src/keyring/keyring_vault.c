/*
 * HashiCorp Vault 2 based keyring provider
 */

#include "postgres.h"

#include <curl/curl.h>

#include "common/base64.h"
#include "common/jsonapi.h"
#include "mb/pg_wchar.h"
#include "utils/builtins.h"

#include "keyring/keyring_api.h"
#include "keyring/keyring_curl.h"
#include "keyring/keyring_vault.h"
#include "pg_tde_defines.h"

#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

/*
 * JSON parser state
 */

typedef enum
{
	JRESP_EXPECT_TOP_DATA,
	JRESP_EXPECT_DATA,
	JRESP_EXPECT_KEY
} JsonVaultRespSemState;

typedef enum
{
	JRESP_MOUNT_INFO_EXPECT_TOPLEVEL_FIELD,
	JRESP_MOUNT_INFO_EXPECT_DATA_START,
	JRESP_MOUNT_INFO_EXPECT_DATA_FIELD,
	JRESP_MOUNT_INFO_EXPECT_TYPE_VALUE,
	JRESP_MOUNT_INFO_EXPECT_VERSION_VALUE,
	JRESP_MOUNT_INFO_EXPECT_OPTIONS_START,
	JRESP_MOUNT_INFO_EXPECT_OPTIONS_FIELD,
} JsonVaultRespMountInfoSemState;

typedef enum
{
	JRESP_F_UNUSED,

	JRESP_F_KEY
} JsonVaultRespField;

typedef struct JsonVaultRespState
{
	JsonVaultRespSemState state;
	JsonVaultRespField field;
	int			level;

	char	   *key;
} JsonVaultRespState;

typedef struct JsonVaultMountInfoState
{
	JsonVaultRespMountInfoSemState state;
	int			level;

	char	   *type;
	char	   *version;
} JsonVaultMountInfoState;

static JsonParseErrorType json_resp_object_start(void *state);
static JsonParseErrorType json_resp_object_end(void *state);
static JsonParseErrorType json_resp_scalar(void *state, char *token, JsonTokenType tokentype);
static JsonParseErrorType json_resp_object_field_start(void *state, char *fname, bool isnull);
static JsonParseErrorType parse_json_response(JsonVaultRespState *parse, JsonLexContext *lex);

static JsonParseErrorType json_mountinfo_object_start(void *state);
static JsonParseErrorType json_mountinfo_object_end(void *state);
static JsonParseErrorType json_mountinfo_scalar(void *state, char *token, JsonTokenType tokentype);
static JsonParseErrorType json_mountinfo_object_field_start(void *state, char *fname, bool isnull);
static JsonParseErrorType parse_vault_mount_info(JsonVaultMountInfoState *state, JsonLexContext *lex);

static char *get_keyring_vault_url(VaultV2Keyring *keyring, const char *key_name);
static bool curl_perform(VaultV2Keyring *keyring, const char *url, CurlString *outStr, long *httpCode, const char *postData);

static void set_key_by_name(GenericKeyring *keyring, KeyInfo *key);
static KeyInfo *get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code);
static void validate(GenericKeyring *keyring);

static const TDEKeyringRoutine keyringVaultV2Routine = {
	.keyring_get_key = get_key_by_name,
	.keyring_store_key = set_key_by_name,
	.keyring_validate = validate,
};

void
InstallVaultV2Keyring(void)
{
	RegisterKeyProviderType(&keyringVaultV2Routine, VAULT_V2_KEY_PROVIDER);
}

static bool
curl_perform(VaultV2Keyring *keyring, const char *url, CurlString *outStr, long *httpCode, const char *postData)
{
	CURLcode	ret;
	struct curl_slist *curlList = NULL;
	char	   *header;

#if KEYRING_DEBUG
	elog(DEBUG1, "Performing Vault HTTP [%s] request to '%s'", postData != NULL ? "POST" : "GET", url);
	if (postData != NULL)
	{
		elog(DEBUG2, "Postdata: '%s'", postData);
	}
#endif
	outStr->ptr = palloc0(1);
	outStr->len = 0;

	if (!curlSetupSession(url, keyring->vault_ca_path, outStr))
		return 0;

	/* Do not let curl resolve "." and ".." segments */
	if (curl_easy_setopt(keyringCurl, CURLOPT_PATH_AS_IS, 1L) != CURLE_OK)
		return 0;

	if (postData != NULL)
	{
		if (curl_easy_setopt(keyringCurl, CURLOPT_POSTFIELDS, postData) != CURLE_OK)
			return 0;
	}

	header = psprintf("X-Vault-Token: %s", keyring->vault_token);
	curlList = curl_slist_append(curlList, header);
	pfree(header);
	if (keyring->vault_namespace != NULL)
	{
		header = psprintf("X-Vault-Namespace: %s", keyring->vault_namespace);
		curlList = curl_slist_append(curlList, header);
		pfree(header);
	}
	if (curlList == NULL)
		return 0;

	if (!curl_slist_append(curlList, "Content-Type: application/json"))
	{
		curl_slist_free_all(curlList);
		return 0;
	}

	if (curl_easy_setopt(keyringCurl, CURLOPT_HTTPHEADER, curlList) != CURLE_OK)
	{
		curl_slist_free_all(curlList);
		return 0;
	}

	ret = curl_easy_perform(keyringCurl);
	if (ret != CURLE_OK)
	{
		elog(LOG, "curl_easy_perform failed with return code: %d", ret);
		curl_slist_free_all(curlList);
		return 0;
	}

	if (curl_easy_getinfo(keyringCurl, CURLINFO_RESPONSE_CODE, httpCode) != CURLE_OK)
	{
		curl_slist_free_all(curlList);
		return 0;
	}

#if KEYRING_DEBUG
	elog(DEBUG2, "Vault response [%li] '%s'", *httpCode, outStr->ptr != NULL ? outStr->ptr : "");
#endif

	curl_slist_free_all(curlList);
	return 1;
}

/*
 * Percent-encode everything except RFC 3986 unreserved characters.
 */
static void
escape_url_segment(const char *in, char *out)
{
	static const char hex[] = "0123456789ABCDEF";

	for (; *in; in++)
	{
		unsigned char c = (unsigned char) *in;

		if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
			(c >= '0' && c <= '9') ||
			c == '-' || c == '_' || c == '.' || c == '~')
			*out++ = c;
		else
		{
			*out++ = '%';
			*out++ = hex[c >> 4];
			*out++ = hex[c & 0xF];
		}
	}
	*out = '\0';
}

/*
 * Vault splits the decoded path on "/" and cleans it, so empty, "." and ".."
 * segments would make the name refer to a different path.
 */
static bool
is_valid_key_path(const char *path)
{
	for (;;)
	{
		size_t		len = strcspn(path, "/");

		if (len == 0 ||
			(len == 1 && path[0] == '.') ||
			(len == 2 && path[0] == '.' && path[1] == '.'))
			return false;
		if (path[len] == '\0')
			return true;
		path += len + 1;
	}
}

static char *
get_keyring_vault_url(VaultV2Keyring *keyring, const char *key_name)
{
	char	   *escaped_name;
	char	   *url;

	Assert(keyring != NULL);
	Assert(key_name != NULL);

	if (!is_valid_key_path(key_name))
		ereport(ERROR,
				errcode(ERRCODE_INVALID_PARAMETER_VALUE),
				errmsg("invalid key name \"%s\" for key provider \"%s\"",
					   key_name, keyring->keyring.provider_name),
				errdetail("Segments of the name separated by \"/\" cannot be empty, \".\" or \"..\"."));

	escaped_name = palloc(strlen(key_name) * 3 + 1);
	escape_url_segment(key_name, escaped_name);

	url = psprintf("%s/v1/%s/data/%s", keyring->vault_url, keyring->vault_mount_path, escaped_name);
	pfree(escaped_name);

	return url;
}

static void
set_key_by_name(GenericKeyring *keyring, KeyInfo *key)
{
	VaultV2Keyring *vault_keyring = (VaultV2Keyring *) keyring;
	char	   *url;
	CurlString	str;
	long		httpCode = 0;
	char		jsonText[512];
	char		keyData[64];
	int			keyLen = 0;

	Assert(key != NULL);

	/*
	 * Since we are only building a very limited JSON with a single base64
	 * string, we build it by hand
	 */
	/* Simpler than using the limited pg json api */
#if PG_VERSION_NUM >= 180000
	keyLen = pg_b64_encode(key->data.data, key->data.len, keyData, 64);
#else
	keyLen = pg_b64_encode((char *) key->data.data, key->data.len, keyData, 64);
#endif
	keyData[keyLen] = 0;

	snprintf(jsonText, 512, "{\"data\":{\"key\":\"%s\"}}", keyData);

#if KEYRING_DEBUG
	elog(DEBUG1, "Sending base64 key: %s", keyData);
#endif

	url = get_keyring_vault_url(vault_keyring, key->name);

	if (!curl_perform(vault_keyring, url, &str, &httpCode, jsonText))
	{
		ereport(ERROR,
				errmsg("HTTP(S) request to keyring provider \"%s\" failed",
					   vault_keyring->keyring.provider_name));
	}

	pfree(url);

	if (str.ptr != NULL)
		pfree(str.ptr);

	if (httpCode / 100 != 2)
		ereport(ERROR,
				errmsg("Invalid HTTP response from keyring provider \"%s\": %ld",
					   vault_keyring->keyring.provider_name, httpCode));
}

static KeyInfo *
get_key_by_name(GenericKeyring *keyring, const char *key_name, KeyringReturnCode *return_code)
{
	VaultV2Keyring *vault_keyring = (VaultV2Keyring *) keyring;
	KeyInfo    *key = NULL;
	char	   *url = NULL;
	CurlString	str;
	long		httpCode = 0;
	JsonParseErrorType json_error;
	JsonLexContext *jlex = NULL;
	JsonVaultRespState parse;

	const char *responseKey;

	*return_code = KEYRING_CODE_SUCCESS;

	url = get_keyring_vault_url(vault_keyring, key_name);

	if (!curl_perform(vault_keyring, url, &str, &httpCode, NULL))
	{
		*return_code = KEYRING_CODE_INVALID_KEY;
		ereport(WARNING,
				errmsg("HTTP(S) request to keyring provider \"%s\" failed",
					   vault_keyring->keyring.provider_name));
		goto cleanup;
	}

	if (httpCode == 404)
	{
		goto cleanup;
	}

	if (httpCode / 100 != 2)
	{
		*return_code = KEYRING_CODE_INVALID_RESPONSE;
		ereport(WARNING,
				errmsg("HTTP(S) request to keyring provider \"%s\" returned invalid response %li",
					   vault_keyring->keyring.provider_name, httpCode));
		goto cleanup;
	}

#if PG_VERSION_NUM >= 170000
	jlex = makeJsonLexContextCstringLen(NULL, str.ptr, str.len, PG_UTF8, true);
#else
	jlex = makeJsonLexContextCstringLen(str.ptr, str.len, PG_UTF8, true);
#endif
	json_error = parse_json_response(&parse, jlex);

	if (json_error != JSON_SUCCESS)
	{
		*return_code = KEYRING_CODE_INVALID_RESPONSE;
		ereport(WARNING,
				errmsg("HTTP(S) request to keyring provider \"%s\" returned incorrect JSON: %s",
					   vault_keyring->keyring.provider_name, json_errdetail(json_error, jlex)));
		goto cleanup;
	}

	if (parse.key == NULL)
	{
		*return_code = KEYRING_CODE_INVALID_RESPONSE;
		ereport(WARNING,
				errmsg("HTTP(S) request to keyring provider \"%s\" returned no key",
					   vault_keyring->keyring.provider_name));
		goto cleanup;
	}

	responseKey = parse.key;

#if KEYRING_DEBUG
	elog(DEBUG1, "Retrieved base64 key: %s", responseKey);
#endif

	key = palloc_object(KeyInfo);
	memset(key->name, 0, sizeof(key->name));
	memcpy(key->name, key_name, strnlen(key_name, sizeof(key->name) - 1));
#if PG_VERSION_NUM >= 180000
	key->data.len = pg_b64_decode(responseKey, strlen(responseKey), key->data.data, MAX_KEY_DATA_SIZE);
#else
	key->data.len = pg_b64_decode(responseKey, strlen(responseKey), (char *) key->data.data, MAX_KEY_DATA_SIZE);
#endif

	if (key->data.len > MAX_KEY_DATA_SIZE)
	{
		*return_code = KEYRING_CODE_INVALID_KEY;
		ereport(WARNING,
				errmsg("keyring provider \"%s\" returned invalid key size: %d",
					   vault_keyring->keyring.provider_name, key->data.len));
		pfree(key);
		key = NULL;
		goto cleanup;
	}

cleanup:
	if (url != NULL)
		pfree(url);
	if (str.ptr != NULL)
		pfree(str.ptr);

#if PG_VERSION_NUM >= 170000
	if (jlex != NULL)
		freeJsonLexContext(jlex);
#endif

	return key;
}

static void
validate(GenericKeyring *keyring)
{
	VaultV2Keyring *vault_keyring = (VaultV2Keyring *) keyring;
	char	   *url;
	CurlString	str;
	long		httpCode = 0;
	JsonParseErrorType json_error;
	JsonLexContext *jlex = NULL;
	JsonVaultMountInfoState parse;

	/*
	 * Validate that the mount has the correct engine type and version.
	 */
	url = psprintf("%s/v1/sys/mounts/%s", vault_keyring->vault_url, vault_keyring->vault_mount_path);

	if (!curl_perform(vault_keyring, url, &str, &httpCode, NULL))
		ereport(ERROR,
				errmsg("HTTP(S) request to keyring provider \"%s\" failed",
					   vault_keyring->keyring.provider_name));

	pfree(url);

	if (httpCode != 200)
	{
		ereport(WARNING,
				errcode(ERRCODE_INVALID_PARAMETER_VALUE),
				errmsg("failed to get mount info for \"%s\" at mountpoint \"%s\" (HTTP %ld)",
					   vault_keyring->vault_url, vault_keyring->vault_mount_path, httpCode));
	}
	else
	{
#if PG_VERSION_NUM >= 170000
		jlex = makeJsonLexContextCstringLen(NULL, str.ptr, str.len, PG_UTF8, true);
#else
		jlex = makeJsonLexContextCstringLen(str.ptr, str.len, PG_UTF8, true);
#endif
		json_error = parse_vault_mount_info(&parse, jlex);

		if (json_error != JSON_SUCCESS)
			ereport(WARNING,
					errcode(ERRCODE_INVALID_JSON_TEXT),
					errmsg("failed to parse mount info for \"%s\" at mountpoint \"%s\": %s",
						   vault_keyring->vault_url, vault_keyring->vault_mount_path, json_errdetail(json_error, jlex)));

		else if (parse.type == NULL)
			ereport(WARNING,
					errcode(ERRCODE_INVALID_PARAMETER_VALUE),
					errmsg("failed to parse mount info for \"%s\" at mountpoint \"%s\": missing type field",
						   vault_keyring->vault_url, vault_keyring->vault_mount_path));

		else if (strcmp(parse.type, "kv") != 0)
			ereport(ERROR,
					errcode(ERRCODE_INVALID_PARAMETER_VALUE),
					errmsg("vault mount at \"%s\" has unsupported engine type \"%s\"",
						   vault_keyring->vault_mount_path, parse.type),
					errhint("The only supported vault engine type is Key/Value version \"2\""));

		else if (parse.version == NULL)
			ereport(ERROR,
					errcode(ERRCODE_INVALID_PARAMETER_VALUE),
					errmsg("failed to parse mount info for \"%s\" at mountpoint \"%s\": missing version field",
						   vault_keyring->vault_url, vault_keyring->vault_mount_path));

		else if (strcmp(parse.version, "2") != 0)
			ereport(ERROR,
					errcode(ERRCODE_INVALID_PARAMETER_VALUE),
					errmsg("vault mount at \"%s\" has unsupported Key/Value engine version \"%s\"",
						   vault_keyring->vault_mount_path, parse.version),
					errhint("The only supported vault engine type is Key/Value version \"2\""));

#if PG_VERSION_NUM >= 170000
		if (jlex != NULL)
			freeJsonLexContext(jlex);
#endif
	}

	/*
	 * Validate that we can read the secrets at the mount point.
	 */
	url = psprintf("%s/v1/%s/metadata/?list=true",
				   vault_keyring->vault_url, vault_keyring->vault_mount_path);

	if (!curl_perform(vault_keyring, url, &str, &httpCode, NULL))
		ereport(ERROR,
				errmsg("HTTP(S) request to keyring provider \"%s\" failed",
					   vault_keyring->keyring.provider_name));

	pfree(url);

	/* If the mount point doesn't have any secrets yet, we'll get a 404. */
	if (httpCode != 200 && httpCode != 404)
		ereport(ERROR,
				errcode(ERRCODE_INVALID_PARAMETER_VALUE),
				errmsg("Listing secrets of \"%s\" at mountpoint \"%s\" failed",
					   vault_keyring->vault_url, vault_keyring->vault_mount_path));

	if (str.ptr != NULL)
		pfree(str.ptr);
}

/*
 * JSON parser routines for key response
 *
 * We expect the response in the form of:
 * {
 * ...
 *   "data": {
 *     "data": {
 *       "key": "key_value"
 *     },
 *   }
 * ...
 * }
 *
 * the rest fields are ignored
 */

static JsonParseErrorType
parse_json_response(JsonVaultRespState *parse, JsonLexContext *lex)
{
	JsonSemAction sem;

	parse->state = JRESP_EXPECT_TOP_DATA;
	parse->level = -1;
	parse->field = JRESP_F_UNUSED;
	parse->key = NULL;

	sem.semstate = parse;
	sem.object_start = json_resp_object_start;
	sem.object_end = json_resp_object_end;
	sem.array_start = NULL;
	sem.array_end = NULL;
	sem.object_field_start = json_resp_object_field_start;
	sem.object_field_end = NULL;
	sem.array_element_start = NULL;
	sem.array_element_end = NULL;
	sem.scalar = json_resp_scalar;

	return pg_parse_json(lex, &sem);
}

/*
 * Invoked at the start of each object in the JSON document.
 *
 * It just keeps track of the current nesting level
 */
static JsonParseErrorType
json_resp_object_start(void *state)
{
	((JsonVaultRespState *) state)->level++;

	return JSON_SUCCESS;
}

/*
 * Invoked at the end of each object in the JSON document.
 *
 * It just keeps track of the current nesting level
 */
static JsonParseErrorType
json_resp_object_end(void *state)
{
	((JsonVaultRespState *) state)->level--;

	return JSON_SUCCESS;
}

/*
 * Invoked at the start of each scalar in the JSON document.
 *
 * We have only the string value of the field. And rely on the state set by
 * `json_resp_object_field_start` for defining what the field is.
 */
static JsonParseErrorType
json_resp_scalar(void *state, char *token, JsonTokenType tokentype)
{
	JsonVaultRespState *parse = state;

	switch (parse->field)
	{
		case JRESP_F_KEY:
			parse->key = token;
			parse->field = JRESP_F_UNUSED;
			break;
		default:
			/* NOP */
			break;
	}
	return JSON_SUCCESS;
}

/*
 * Invoked at the start of each object field in the JSON document.
 *
 * Based on the given field name and the level we set the state so that when
 * we get the value, we know what is it and where to assign it.
 */
static JsonParseErrorType
json_resp_object_field_start(void *state, char *fname, bool isnull)
{
	JsonVaultRespState *parse = state;

	switch (parse->state)
	{
		case JRESP_EXPECT_TOP_DATA:
			if (strcmp(fname, "data") == 0 && parse->level == 0)
				parse->state = JRESP_EXPECT_DATA;
			break;
		case JRESP_EXPECT_DATA:
			if (strcmp(fname, "data") == 0 && parse->level == 1)
				parse->state = JRESP_EXPECT_KEY;
			break;
		case JRESP_EXPECT_KEY:
			if (strcmp(fname, "key") == 0 && parse->level == 2)
				parse->field = JRESP_F_KEY;
			break;
		default:
			/* NOP */
			break;
	}

	return JSON_SUCCESS;
}

/*
 * JSON parser routines for mount info
 *
 * We expect the response in the form of:
 * {
 * ...
 *   "data": {
 *     "type": "kv",
 *     "options": {
 *        "version": "2"
 *     }
 *   }
 * ...
 * }
 *
 * the rest fields are ignored
 */

static JsonParseErrorType
parse_vault_mount_info(JsonVaultMountInfoState *state, JsonLexContext *lex)
{
	JsonSemAction sem;

	state->state = JRESP_MOUNT_INFO_EXPECT_TOPLEVEL_FIELD;
	state->type = NULL;
	state->version = NULL;
	state->level = -1;

	memset(&sem, 0, sizeof(sem));
	sem.semstate = state;
	sem.object_start = json_mountinfo_object_start;
	sem.object_end = json_mountinfo_object_end;
	sem.scalar = json_mountinfo_scalar;
	sem.object_field_start = json_mountinfo_object_field_start;

	return pg_parse_json(lex, &sem);
}

static JsonParseErrorType
json_mountinfo_object_start(void *state)
{
	JsonVaultMountInfoState *parse = (JsonVaultMountInfoState *) state;

	switch (parse->state)
	{
		case JRESP_MOUNT_INFO_EXPECT_DATA_START:
			parse->state = JRESP_MOUNT_INFO_EXPECT_DATA_FIELD;
			break;
		case JRESP_MOUNT_INFO_EXPECT_OPTIONS_START:
			parse->state = JRESP_MOUNT_INFO_EXPECT_OPTIONS_FIELD;
			break;
		default:
			/* NOP */
			break;
	}

	parse->level++;

	return JSON_SUCCESS;
}

static JsonParseErrorType
json_mountinfo_object_end(void *state)
{
	JsonVaultMountInfoState *parse = (JsonVaultMountInfoState *) state;

	if (parse->state == JRESP_MOUNT_INFO_EXPECT_OPTIONS_FIELD)
		parse->state = JRESP_MOUNT_INFO_EXPECT_DATA_FIELD;
	else if (parse->state == JRESP_MOUNT_INFO_EXPECT_DATA_FIELD && parse->level == 1)
		parse->state = JRESP_MOUNT_INFO_EXPECT_TOPLEVEL_FIELD;

	parse->level--;

	return JSON_SUCCESS;
}

static JsonParseErrorType
json_mountinfo_scalar(void *state, char *token, JsonTokenType tokentype)
{
	JsonVaultMountInfoState *parse = (JsonVaultMountInfoState *) state;

	switch (parse->state)
	{
		case JRESP_MOUNT_INFO_EXPECT_TYPE_VALUE:
			parse->type = token;
			parse->state = JRESP_MOUNT_INFO_EXPECT_DATA_FIELD;
			break;
		case JRESP_MOUNT_INFO_EXPECT_VERSION_VALUE:
			parse->version = token;
			parse->state = JRESP_MOUNT_INFO_EXPECT_OPTIONS_FIELD;
			break;
		case JRESP_MOUNT_INFO_EXPECT_OPTIONS_START:

			/*
			 * Reset "options" object expectations if we got scalar. Most
			 * likely just a null.
			 */
			parse->state = JRESP_MOUNT_INFO_EXPECT_DATA_FIELD;
			break;
		case JRESP_MOUNT_INFO_EXPECT_DATA_START:

			/*
			 * Reset "data" object expectations if we got scalar. Most likely
			 * just a null.
			 */
			parse->state = JRESP_MOUNT_INFO_EXPECT_TOPLEVEL_FIELD;
			break;
		default:
			/* NOP */
			break;
	}

	return JSON_SUCCESS;
}

static JsonParseErrorType
json_mountinfo_object_field_start(void *state, char *fname, bool isnull)
{
	JsonVaultMountInfoState *parse = (JsonVaultMountInfoState *) state;

	switch (parse->state)
	{
		case JRESP_MOUNT_INFO_EXPECT_TOPLEVEL_FIELD:
			if (parse->level == 0)
			{
				if (strcmp(fname, "data") == 0)
				{
					parse->state = JRESP_MOUNT_INFO_EXPECT_DATA_START;
					break;
				}
			}
			break;

		case JRESP_MOUNT_INFO_EXPECT_DATA_FIELD:
			if (parse->level == 1)
			{
				if (strcmp(fname, "type") == 0)
				{
					parse->state = JRESP_MOUNT_INFO_EXPECT_TYPE_VALUE;
					break;
				}

				if (strcmp(fname, "options") == 0)
				{
					parse->state = JRESP_MOUNT_INFO_EXPECT_OPTIONS_START;
					break;
				}
			}
			break;

		case JRESP_MOUNT_INFO_EXPECT_OPTIONS_FIELD:
			if (parse->level == 2)
			{
				if (strcmp(fname, "version") == 0)
				{
					parse->state = JRESP_MOUNT_INFO_EXPECT_VERSION_VALUE;
					break;
				}
			}
			break;

		default:
			/* NOP */
			break;
	}

	pfree(fname);
	return JSON_SUCCESS;
}
