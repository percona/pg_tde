/*-------------------------------------------------------------------------
 *
 * pg_tde_shmem.h
 * src/include/common/pg_tde_shmem.h
 *
 *-------------------------------------------------------------------------
 */
#ifndef PG_TDE_SHMEM_H
#define PG_TDE_SHMEM_H
#include "postgres.h"
#include "storage/shmem.h"
#include "lib/dshash.h"
#include "utils/dsa.h"

typedef struct TDEShmemSetupRoutine
{
    Size (*init_shared_state)(void *raw_dsa_area);
    void (*shmem_kill)(int code, Datum arg);
    Size (*required_shared_mem_size)(void);
    void (*init_dsa_area_objects)(dsa_area *dsa, void *raw_dsa_area);
} TDEShmemSetupRoutine;

extern void RegisterShmemRequest(const TDEShmemSetupRoutine *routine);
extern void TdeShmemInit(void);
extern Size TdeRequiredSharedMemorySize(void);

#endif /*PG_TDE_SHMEM_H*/