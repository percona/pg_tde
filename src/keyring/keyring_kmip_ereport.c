
#include "postgres.h"

#include "keyring/keyring_kmip.h"
#include "catalog/keyring_min.h"
#ifdef FRONTEND
#include "pg_tde_fe.h"
#endif

void kmip_ereport(bool throw_error, const char *msg, int errCode)
{
    if (errCode != 0)
    {
        ereport(throw_error, msg, errCode);
    }
    else
    {
        ereport(throw_error, msg);
    }
}