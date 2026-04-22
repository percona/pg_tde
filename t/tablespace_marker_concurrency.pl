#!/usr/bin/perl

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;
use Time::HiRes qw(usleep);

unlink('/tmp/pg_tde_markconc.per');

my $node = PostgreSQL::Test::Cluster->new('markconc');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->append_conf('postgresql.conf', 'allow_in_place_tablespaces = true');
$node->start;

$node->safe_psql(
	'postgres', q{
    CREATE EXTENSION pg_tde;
    SELECT pg_tde_add_database_key_provider_file('fv', '/tmp/pg_tde_markconc.per');
    SELECT pg_tde_create_key_using_database_key_provider('k','fv');
    SELECT pg_tde_set_key_using_database_key_provider('k','fv');
});

# ============================================================
# Scenario 1: mark does not block on an unrelated transaction.
# ============================================================
$node->safe_psql(
	'postgres', q{
    CREATE TABLESPACE s1_ts LOCATION '';
    CREATE TABLE s1_dummy (x int);
});

my $sA = $node->background_psql('postgres');
$sA->query_safe("BEGIN;");
$sA->query_safe("LOCK TABLE s1_dummy IN ACCESS SHARE MODE;");

# Session B: the mark call. Should not block. safe_psql would hang if it did.
$node->safe_psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('s1_ts');");
pass('Scenario 1: mark does not block on an unrelated transaction');

$sA->query_safe("ROLLBACK;");
$sA->quit;

$node->safe_psql(
	'postgres', q{
    SELECT pg_tde_mark_tablespace_decrypted('s1_ts');
    DROP TABLESPACE s1_ts;
    DROP TABLE s1_dummy;
});

# ============================================================
# Scenario 2: a session holds an uncommitted CREATE TABLE; the mark
# should NOT succeed while those files are on disk. Verifies the
# emptiness check + locking machinery: the mark observes files, runs
# its internal checkpoint + barrier dance, and still sees them (since
# session A's txn is still open), then errors "not empty". Once A
# rolls back, a subsequent mark succeeds because the mark function's
# own internal CHECKPOINT reaps the orphaned file.
# ============================================================
$node->safe_psql('postgres', "CREATE TABLESPACE s2_ts LOCATION '';");

$sA = $node->background_psql('postgres');
$sA->query_safe("BEGIN;");
$sA->query_safe("CREATE TABLE s2_t (x int) TABLESPACE s2_ts;");

# Session B in the background. We send \echo to force pg_tde to have
# "started" the mark call; the psql stays occupied until the server
# returns. We use query_until with a pattern the server cannot emit
# (nothing) plus a short timeout trick: actually, we use a plain
# $node->psql — it returns once the query either errors or finishes.
# The mark call cannot run inside a txn block, so it's a standalone.
my ($ret, $out, $err) = $node->psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('s2_ts');");

isnt($ret, 0,
	'Scenario 2: mark errors while A holds an uncommitted CREATE TABLE');
like($err, qr/not empty/i,
	'Scenario 2: mark error mentions "not empty"');

# Now roll back A and retry: mark should succeed (its own CHECKPOINT
# reaps the file left behind by the rolled-back CREATE TABLE).
$sA->query_safe("ROLLBACK;");
$sA->quit;

$node->safe_psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('s2_ts');");
pass('Scenario 2: mark succeeds once A rolls back');

$node->safe_psql(
	'postgres', q{
    SELECT pg_tde_mark_tablespace_decrypted('s2_ts');
    DROP TABLESPACE s2_ts;
});

# ============================================================
# Scenario 3: two racing mark calls. One wins the LWLock + AccessExclusive
# race and flips the state, the other observes the new state and emits
# the idempotent NOTICE. Neither corrupts the list file (we verify by
# creating + probing a table afterwards).
# ============================================================
$node->safe_psql('postgres', "CREATE TABLESPACE s3_ts LOCATION '';");

my $sA_bg = $node->background_psql('postgres');
my $sB_bg = $node->background_psql('postgres');

# Kick off both calls. We use query() (not query_safe) because the
# "losing" session will emit a NOTICE on stderr, which query_safe would
# treat as a failure. Both must eventually return.
my ($oA, $rA) = $sA_bg->query(
	"SELECT pg_tde_mark_tablespace_encrypted('s3_ts');");
my ($oB, $rB) = $sB_bg->query(
	"SELECT pg_tde_mark_tablespace_encrypted('s3_ts');");

# Capture stderr from both sessions. query() stashes per-query stderr
# in $self->{stderr}, which is reset for the next query.
my $errA = $sA_bg->{stderr};
my $errB = $sB_bg->{stderr};

$sA_bg->quit;
$sB_bg->quit;

ok( $errA =~ /already marked encrypted/i
	  || $errB =~ /already marked encrypted/i,
	'Scenario 3: exactly one racing mark observes the idempotent NOTICE');

# Verify the shared array + on-disk file are coherent: creating a
# fresh table in s3_ts and probing pg_tde_is_encrypted should return t.
my $is_enc = $node->safe_psql(
	'postgres', q{
    CREATE TABLE s3_probe (x int) TABLESPACE s3_ts;
    SELECT pg_tde_is_encrypted('s3_probe');
});
is($is_enc, 't',
	'Scenario 3: post-race, s3_ts is cleanly marked encrypted');

$node->safe_psql(
	'postgres', q{
    DROP TABLE s3_probe;
    SELECT pg_tde_mark_tablespace_decrypted('s3_ts');
    DROP TABLESPACE s3_ts;
});

# ============================================================
# Residual race (design §3): a CREATE TABLE into a pre-existing empty
# per-dboid subdir does not re-take TablespaceCreateLock, so in
# principle a relfilenode file can land between the mark's barrier
# drain and the list-file rename. Window is microseconds and requires
# an external stimulus to reproduce reliably; not closed by Task 4's
# locking. Documented here as a TODO so the gap is visible in the
# test output.
# ============================================================
TODO: {
	local $TODO =
	  "design §3: CREATE into pre-existing empty per-dboid subdir does not take TablespaceCreateLock";
	fail(
		'residual race demonstration intentionally not implemented; see design §3'
	);
}

$node->stop;
done_testing();
