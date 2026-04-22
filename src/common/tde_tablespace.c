/* src/common/tde_tablespace.c */
#include "postgres.h"

#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

#include "access/xact.h"
#include "access/xlog.h"
#include "access/xloginsert.h"
#include "access/pg_tde_xlog.h"
#include "catalog/pg_tablespace.h"
#include "catalog/pg_tablespace_d.h"
#include "commands/tablespace.h"
#include "executor/spi.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "storage/fd.h"
#include "storage/ipc.h"
#include "storage/lmgr.h"
#include "storage/lwlock.h"
#include "postmaster/bgwriter.h"
#include "storage/procsignal.h"
#include "storage/shmem.h"
#include "utils/acl.h"
#include "utils/builtins.h"

#include "common/pg_tde_utils.h"
#include "common/tde_tablespace.h"

#define LIST_FILE_MAGIC   0x54444553	/* 'TDES' */
#define LIST_FILE_VERSION 1

typedef struct TdeTablespaceState
{
	LWLock		lock;			/* protects below */
	int			count;
	Oid			oids[MAX_ENCRYPTED_TABLESPACES];
} TdeTablespaceState;

typedef struct ListFileHeader
{
	uint32		magic;
	uint32		version;
	uint32		count;
	uint32		reserved;
} ListFileHeader;

static TdeTablespaceState *state = NULL;

static void load_list_file(void);
static void write_list_file(const Oid *oids, int count);
static void list_file_path(char *out, size_t outlen);
static bool tablespace_dir_is_empty(Oid spcOid);

PG_FUNCTION_INFO_V1(pg_tde_mark_tablespace_encrypted);
PG_FUNCTION_INFO_V1(pg_tde_mark_tablespace_decrypted);
PG_FUNCTION_INFO_V1(pg_tde_tablespace_is_encrypted);

static Datum mark_tablespace(FunctionCallInfo fcinfo,
							 bool want_encrypted,
							 const char *sqlname);

Size
pg_tde_tablespace_shmem_size(void)
{
	return MAXALIGN(sizeof(TdeTablespaceState));
}

void
pg_tde_tablespace_shmem_init(void)
{
	bool		found;

	Assert(LWLockHeldByMeInMode(AddinShmemInitLock, LW_EXCLUSIVE));

	state = ShmemInitStruct("pg_tde_tablespace",
							pg_tde_tablespace_shmem_size(),
							&found);
	if (!found)
	{
		LWLockInitialize(&state->lock, LWLockNewTrancheId());
		state->count = 0;
		/* oids[] zeroed by ShmemInitStruct. */
		load_list_file();
	}
	LWLockRegisterTranche(state->lock.tranche, "pg_tde_tablespace");
}

bool
tablespace_is_encrypted(Oid spcOid)
{
	bool		hit = false;

	if (!OidIsValid(spcOid))
		return false;
	if (spcOid == DEFAULTTABLESPACE_OID || spcOid == GLOBALTABLESPACE_OID)
		return false;

	Assert(state != NULL);
	LWLockAcquire(&state->lock, LW_SHARED);
	for (int i = 0; i < state->count; i++)
	{
		if (state->oids[i] == spcOid)
		{
			hit = true;
			break;
		}
	}
	LWLockRelease(&state->lock);
	return hit;
}

Datum
pg_tde_mark_tablespace_encrypted(PG_FUNCTION_ARGS)
{
	return mark_tablespace(fcinfo, true, "pg_tde_mark_tablespace_encrypted");
}

Datum
pg_tde_mark_tablespace_decrypted(PG_FUNCTION_ARGS)
{
	return mark_tablespace(fcinfo, false, "pg_tde_mark_tablespace_decrypted");
}

Datum
pg_tde_tablespace_is_encrypted(PG_FUNCTION_ARGS)
{
	Oid			spcOid = PG_GETARG_OID(0);

	PG_RETURN_BOOL(tablespace_is_encrypted(spcOid));
}

static Datum
mark_tablespace(FunctionCallInfo fcinfo, bool want_encrypted, const char *sqlname)
{
	text	   *ts_name_text = PG_GETARG_TEXT_PP(0);
	char	   *ts_name = text_to_cstring(ts_name_text);
	Oid			spcOid;
	bool		currently_encrypted;

	/* (1) Outside tx block only. */
	PreventInTransactionBlock(true /* isTopLevel */ , sqlname);
	if (SPI_inside_nonatomic_context())
		ereport(ERROR,
				errcode(ERRCODE_ACTIVE_SQL_TRANSACTION),
				errmsg("%s cannot run inside a transaction block", sqlname));

	/* (2) Resolve name. */
	spcOid = get_tablespace_oid(ts_name, false);

	/* (3) Reject pg_default / pg_global. */
	if (spcOid == DEFAULTTABLESPACE_OID || spcOid == GLOBALTABLESPACE_OID)
		ereport(ERROR,
				errcode(ERRCODE_FEATURE_NOT_SUPPORTED),
				errmsg("cannot mark the %s tablespace",
					   spcOid == DEFAULTTABLESPACE_OID ? "default" : "global"));

	/* (4) Ownership. Match ALTER TABLESPACE: tablespace owner or superuser. */
	if (!object_ownercheck(TableSpaceRelationId, spcOid, GetUserId()))
		aclcheck_error(ACLCHECK_NOT_OWNER, OBJECT_TABLESPACE, ts_name);

	/*
	 * (5) Serialize against DropTableSpace and TablespaceCreateDbspace.
	 */
	LWLockAcquire(TablespaceCreateLock, LW_EXCLUSIVE);

	/*
	 * (6) Ask all backends to release smgr handles into this tablespace so
	 * we can trust the filesystem picture below. Must release LWLock around
	 * the barrier since it can take arbitrarily long.
	 */
	LWLockRelease(TablespaceCreateLock);
	WaitForProcSignalBarrier(EmitProcSignalBarrier(PROCSIGNAL_BARRIER_SMGRRELEASE));
	LWLockAcquire(TablespaceCreateLock, LW_EXCLUSIVE);

	/*
	 * (7) Lock the tablespace object itself to block ALTER TABLESPACE and
	 * racing pg_tde mark calls. Released at transaction end.
	 */
	LockSharedObject(TableSpaceRelationId, spcOid, 0, AccessExclusiveLock);

	/* (8) Idempotent NOTICE — short-circuit regardless of emptiness. */
	LWLockAcquire(&state->lock, LW_SHARED);
	currently_encrypted = false;
	for (int i = 0; i < state->count; i++)
	{
		if (state->oids[i] == spcOid)
		{
			currently_encrypted = true;
			break;
		}
	}
	LWLockRelease(&state->lock);

	if (currently_encrypted == want_encrypted)
	{
		LWLockRelease(TablespaceCreateLock);
		ereport(NOTICE,
				errmsg("tablespace \"%s\" is already marked %s",
					   ts_name, want_encrypted ? "encrypted" : "decrypted"));
		PG_RETURN_VOID();
	}

	/*
	 * (9) Emptiness enforcement — only applies on a real state change.
	 * DROP TABLE defers file unlink to the next checkpoint, so a freshly
	 * dropped relation can leave a lingering file in the per-dboid dir.
	 * Match DropTableSpace: if the first walk sees files, force a
	 * checkpoint + smgr-release barrier and try again.
	 */
	if (!tablespace_dir_is_empty(spcOid))
	{
		/*
		 * Note: unlike the initial barrier drain above, we hold
		 * TablespaceCreateLock through RequestCheckpoint to match
		 * DropTableSpace's ordering — so no backend can create a new
		 * per-dboid subdir while the checkpoint drains pending unlinks.
		 * Only the barrier portion releases the lock.
		 */
		RequestCheckpoint(CHECKPOINT_IMMEDIATE | CHECKPOINT_FORCE | CHECKPOINT_WAIT);
		LWLockRelease(TablespaceCreateLock);
		WaitForProcSignalBarrier(EmitProcSignalBarrier(PROCSIGNAL_BARRIER_SMGRRELEASE));
		LWLockAcquire(TablespaceCreateLock, LW_EXCLUSIVE);

		if (!tablespace_dir_is_empty(spcOid))
		{
			LWLockRelease(TablespaceCreateLock);
			ereport(ERROR,
					errcode(ERRCODE_OBJECT_IN_USE),
					errmsg("tablespace \"%s\" is not empty", ts_name),
					errhint("Drop all objects in the tablespace before changing its encryption mark."));
		}
	}

	/*
	 * (10) WAL-log the mark, rewrite the on-disk list, flush, then mutate
	 * the shared array — all under the exclusive state->lock. Ordering matches
	 * design §5: WAL insert → file rewrite → XLogFlush → array update.
	 *
	 * The shared array is the last thing touched so a concurrent reader on
	 * another CPU either sees the full old state or the full new state, and
	 * a crash between any two steps is recoverable from WAL replay.
	 */
	LWLockAcquire(&state->lock, LW_EXCLUSIVE);

	/* Capacity check on mark-encrypted. */
	if (want_encrypted && state->count >= MAX_ENCRYPTED_TABLESPACES)
	{
		LWLockRelease(&state->lock);
		LWLockRelease(TablespaceCreateLock);
		ereport(ERROR,
				errcode(ERRCODE_CONFIGURATION_LIMIT_EXCEEDED),
				errmsg("cannot mark more than %d tablespaces as encrypted",
					   MAX_ENCRYPTED_TABLESPACES));
	}

	/* Snapshot the target array so we can write the file pre-mutation. */
	{
		Oid			new_oids[MAX_ENCRYPTED_TABLESPACES];
		int			new_count = state->count;
		uint8		info;
		XLogRecPtr	lsn;

		memcpy(new_oids, state->oids, sizeof(Oid) * state->count);

		if (want_encrypted)
		{
			new_oids[new_count++] = spcOid;
		}
		else
		{
			for (int i = 0; i < new_count; i++)
			{
				if (new_oids[i] == spcOid)
				{
					new_oids[i] = new_oids[--new_count];
					new_oids[new_count] = InvalidOid;
					break;
				}
			}
		}

		info = want_encrypted
			? XLOG_TDE_MARK_TABLESPACE_ENCRYPTED
			: XLOG_TDE_MARK_TABLESPACE_DECRYPTED;

		/*
		 * Point of no return: once XLogInsert has buffered the record, any
		 * ERROR before the array mutation would leave WAL and shared state
		 * disagreeing (another backend could flush the record, making it
		 * durable even though this session rolled back). Promote any such
		 * failure to PANIC so crash recovery replays the record and
		 * converges state.
		 */
		START_CRIT_SECTION();

		XLogBeginInsert();
		XLogRegisterData((char *) &spcOid, sizeof(Oid));
		lsn = XLogInsert(RM_TDERMGR_ID, info);

		write_list_file(new_oids, new_count);

		XLogFlush(lsn);

		memcpy(state->oids, new_oids, sizeof(Oid) * MAX_ENCRYPTED_TABLESPACES);
		state->count = new_count;

		END_CRIT_SECTION();
	}

	LWLockRelease(&state->lock);
	LWLockRelease(TablespaceCreateLock);

	PG_RETURN_VOID();
}

/*
 * Redo helper invoked from tdeheap_rmgr_redo. Idempotent: replaying the same
 * record twice leaves the array unchanged. PANICs on capacity overflow, which
 * should never happen because the primary enforces the cap before inserting
 * the WAL record.
 */
void
pg_tde_tablespace_marker_redo(Oid spcOid, bool want_encrypted)
{
	bool		currently_encrypted = false;
	Oid			new_oids[MAX_ENCRYPTED_TABLESPACES];
	int			new_count;

	Assert(state != NULL);
	LWLockAcquire(&state->lock, LW_EXCLUSIVE);

	for (int i = 0; i < state->count; i++)
	{
		if (state->oids[i] == spcOid)
		{
			currently_encrypted = true;
			break;
		}
	}

	if (currently_encrypted == want_encrypted)
	{
		LWLockRelease(&state->lock);
		return;
	}

	new_count = state->count;
	memcpy(new_oids, state->oids, sizeof(Oid) * state->count);

	if (want_encrypted)
	{
		if (new_count >= MAX_ENCRYPTED_TABLESPACES)
		{
			LWLockRelease(&state->lock);
			ereport(PANIC,
					errmsg("pg_tde marker redo: capacity exceeded"));
		}
		new_oids[new_count++] = spcOid;
	}
	else
	{
		for (int i = 0; i < new_count; i++)
		{
			if (new_oids[i] == spcOid)
			{
				new_oids[i] = new_oids[--new_count];
				new_oids[new_count] = InvalidOid;
				break;
			}
		}
	}

	write_list_file(new_oids, new_count);

	memcpy(state->oids, new_oids, sizeof(Oid) * MAX_ENCRYPTED_TABLESPACES);
	state->count = new_count;

	LWLockRelease(&state->lock);
}

/*
 * DROP TABLESPACE post-hook. Called AFTER standard_ProcessUtility has
 * successfully dropped the tablespace. Emits a decrypt WAL record so the
 * replica's list file converges with the primary's, and removes the OID
 * from the primary's shared array + list file.
 *
 * Safe to call with any OID: no-ops if the OID isn't currently marked.
 * No emptiness/ownership checks (standard_ProcessUtility already enforced them).
 */
void
pg_tde_tablespace_drop_hook(Oid spcOid)
{
	Oid			new_oids[MAX_ENCRYPTED_TABLESPACES];
	int			new_count;
	bool		was_marked = false;
	XLogRecPtr	lsn;

	if (!OidIsValid(spcOid))
		return;
	if (spcOid == DEFAULTTABLESPACE_OID || spcOid == GLOBALTABLESPACE_OID)
		return;

	Assert(state != NULL);
	LWLockAcquire(&state->lock, LW_EXCLUSIVE);

	new_count = state->count;
	memcpy(new_oids, state->oids, sizeof(Oid) * state->count);

	for (int i = 0; i < new_count; i++)
	{
		if (new_oids[i] == spcOid)
		{
			new_oids[i] = new_oids[--new_count];
			new_oids[new_count] = InvalidOid;
			was_marked = true;
			break;
		}
	}

	if (!was_marked)
	{
		LWLockRelease(&state->lock);
		return;
	}

	/*
	 * Point of no return: see mark_tablespace() for the reasoning. Any
	 * failure after XLogInsert must crash the server so WAL redo converges
	 * state.
	 */
	START_CRIT_SECTION();

	XLogBeginInsert();
	XLogRegisterData((char *) &spcOid, sizeof(Oid));
	lsn = XLogInsert(RM_TDERMGR_ID, XLOG_TDE_MARK_TABLESPACE_DECRYPTED);

	write_list_file(new_oids, new_count);

	XLogFlush(lsn);

	memcpy(state->oids, new_oids, sizeof(Oid) * MAX_ENCRYPTED_TABLESPACES);
	state->count = new_count;

	END_CRIT_SECTION();

	LWLockRelease(&state->lock);
}

/*
 * Return true if the tablespace directory contains no populated per-database
 * subdirectory. Matches DropTableSpace's tolerance: ENOENT on the version dir
 * (never populated) counts as empty, as do empty per-dboid subdirectories
 * left behind after DROP TABLE.
 */
static bool
tablespace_dir_is_empty(Oid spcOid)
{
	char		path[MAXPGPATH];
	DIR		   *dir;
	struct dirent *de;

	snprintf(path, sizeof(path), "pg_tblspc/%u/%s",
			 spcOid, TABLESPACE_VERSION_DIRECTORY);
	dir = AllocateDir(path);
	if (dir == NULL)
	{
		if (errno == ENOENT)
			return true;		/* never populated */
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open directory \"%s\": %m", path));
	}

	while ((de = ReadDir(dir, path)) != NULL)
	{
		char		subpath[MAXPGPATH];
		DIR		   *sub;
		struct dirent *sd;
		bool		subempty = true;

		if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0)
			continue;

		snprintf(subpath, sizeof(subpath), "%s/%s", path, de->d_name);
		sub = AllocateDir(subpath);
		if (sub == NULL)
		{
			if (errno == ENOENT)
				continue;		/* vanished between readdir and open */
			FreeDir(dir);
			ereport(ERROR,
					errcode_for_file_access(),
					errmsg("could not open directory \"%s\": %m", subpath));
		}

		while ((sd = ReadDir(sub, subpath)) != NULL)
		{
			if (strcmp(sd->d_name, ".") == 0 || strcmp(sd->d_name, "..") == 0)
				continue;
			subempty = false;
			break;
		}
		FreeDir(sub);
		if (!subempty)
		{
			FreeDir(dir);
			return false;
		}
	}
	FreeDir(dir);
	return true;
}

static void
list_file_path(char *out, size_t outlen)
{
	snprintf(out, outlen, "%s/encrypted_tablespaces.lst",
			 pg_tde_get_data_dir());
}

static void
load_list_file(void)
{
	char		path[MAXPGPATH];
	int			fd;
	ListFileHeader hdr;
	ssize_t		n;

	list_file_path(path, sizeof(path));
	fd = OpenTransientFile(path, O_RDONLY | PG_BINARY);
	if (fd < 0)
	{
		if (errno == ENOENT)
			return;				/* fresh install — empty list is fine */
		ereport(FATAL,
				errcode_for_file_access(),
				errmsg("could not open \"%s\": %m", path));
	}
	n = read(fd, &hdr, sizeof(hdr));
	if (n != sizeof(hdr) || hdr.magic != LIST_FILE_MAGIC || hdr.version != LIST_FILE_VERSION)
	{
		CloseTransientFile(fd);
		ereport(FATAL,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("\"%s\" has bad header", path));
	}
	if (hdr.count > MAX_ENCRYPTED_TABLESPACES)
	{
		CloseTransientFile(fd);
		ereport(FATAL,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("\"%s\" claims %u entries, cap is %d",
					   path, hdr.count, MAX_ENCRYPTED_TABLESPACES));
	}
	n = read(fd, state->oids, sizeof(Oid) * hdr.count);
	CloseTransientFile(fd);
	if (n != (ssize_t) (sizeof(Oid) * hdr.count))
		ereport(FATAL,
				errcode(ERRCODE_DATA_CORRUPTED),
				errmsg("\"%s\" truncated", path));
	state->count = hdr.count;
}

static void
write_list_file(const Oid *oids, int count)
{
	char		path[MAXPGPATH];
	char		tmp[MAXPGPATH];
	int			fd;
	int			save_errno = 0;
	const char *what = NULL;
	ListFileHeader hdr;

	list_file_path(path, sizeof(path));
	snprintf(tmp, sizeof(tmp), "%s.tmp", path);

	fd = OpenTransientFile(tmp,
						   O_WRONLY | O_CREAT | O_TRUNC | PG_BINARY);
	if (fd < 0)
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not open \"%s\": %m", tmp));

	hdr.magic = LIST_FILE_MAGIC;
	hdr.version = LIST_FILE_VERSION;
	hdr.count = count;
	hdr.reserved = 0;

	if (write(fd, &hdr, sizeof(hdr)) != sizeof(hdr))
	{
		save_errno = errno ? errno : ENOSPC;
		what = "write header";
	}
	else if (count > 0 &&
			 write(fd, oids, sizeof(Oid) * count)
			 != (ssize_t) (sizeof(Oid) * count))
	{
		save_errno = errno ? errno : ENOSPC;
		what = "write body";
	}
	else if (pg_fsync(fd) != 0)
	{
		save_errno = errno;
		what = "fsync";
	}
	CloseTransientFile(fd);

	if (save_errno != 0)
	{
		errno = save_errno;
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not %s of \"%s\": %m", what, tmp));
	}

	if (durable_rename(tmp, path, ERROR) != 0)
		ereport(ERROR,
				errcode_for_file_access(),
				errmsg("could not rename \"%s\" to \"%s\": %m", tmp, path));
}
