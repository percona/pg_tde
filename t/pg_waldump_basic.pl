
# Copyright (c) 2021-2024, PostgreSQL Global Development Group

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

unlink('/tmp/pg_waldump_basic.per');

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf(
	'postgresql.conf', q{
autovacuum = off
checkpoint_timeout = 1h

# for standbydesc
archive_mode=on
archive_command=''

# for XLOG_HEAP_TRUNCATE
wal_level=logical

# WAL Encryption
shared_preload_libraries = 'pg_tde'
});
$node->start;

$node->safe_psql('postgres', "CREATE EXTENSION pg_tde;");
$node->safe_psql('postgres',
	"SELECT pg_tde_add_global_key_provider_file('file-keyring-wal', '/tmp/pg_waldump_basic.per');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('server-key', 'file-keyring-wal');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'file-keyring-wal');"
);

$node->append_conf(
	'postgresql.conf', q{
pg_tde.wal_encrypt = on
});
$node->restart;

my ($start_lsn, $start_walfile) = split /\|/,
  $node->safe_psql('postgres',
	q{SELECT pg_current_wal_insert_lsn(), pg_walfile_name(pg_current_wal_insert_lsn())}
  );

$node->safe_psql(
	'postgres', q{
-- heap, btree, hash, sequence
CREATE TABLE t1 (a int GENERATED ALWAYS AS IDENTITY, b text);
CREATE INDEX i1a ON t1 USING btree (a);
CREATE INDEX i1b ON t1 USING hash (b);
INSERT INTO t1 VALUES (default, 'one'), (default, 'two');
DELETE FROM t1 WHERE b = 'one';
TRUNCATE t1;

-- abort
START TRANSACTION;
INSERT INTO t1 VALUES (default, 'three');
ROLLBACK;

-- unlogged/init fork
CREATE UNLOGGED TABLE t2 (x int);
CREATE INDEX i2 ON t2 USING btree (x);
INSERT INTO t2 SELECT generate_series(1, 10);

-- gin
CREATE TABLE gin_idx_tbl (id bigserial PRIMARY KEY, data jsonb);
CREATE INDEX gin_idx ON gin_idx_tbl USING gin (data);
INSERT INTO gin_idx_tbl
    WITH random_json AS (
        SELECT json_object_agg(key, trunc(random() * 10)) as json_data
            FROM unnest(array['a', 'b', 'c']) as u(key))
          SELECT generate_series(1,500), json_data FROM random_json;

-- gist, spgist
CREATE TABLE gist_idx_tbl (p point);
CREATE INDEX gist_idx ON gist_idx_tbl USING gist (p);
CREATE INDEX spgist_idx ON gist_idx_tbl USING spgist (p);
INSERT INTO gist_idx_tbl (p) VALUES (point '(1, 1)'), (point '(3, 2)'), (point '(6, 3)');

-- brin
CREATE TABLE brin_idx_tbl (col1 int, col2 text, col3 text );
CREATE INDEX brin_idx ON brin_idx_tbl USING brin (col1, col2, col3) WITH (autosummarize=on);
INSERT INTO brin_idx_tbl SELECT generate_series(1, 10000), 'dummy', 'dummy';
UPDATE brin_idx_tbl SET col2 = 'updated' WHERE col1 BETWEEN 1 AND 5000;
SELECT brin_summarize_range('brin_idx', 0);
SELECT brin_desummarize_range('brin_idx', 0);

VACUUM;

-- logical message
SELECT pg_logical_emit_message(true, 'foo', 'bar');

-- relmap
VACUUM FULL pg_authid;

-- database
CREATE DATABASE d1;
DROP DATABASE d1;
});

my $tblspc_path = PostgreSQL::Test::Utils::tempdir_short();

$node->safe_psql(
	'postgres', qq{
CREATE TABLESPACE ts1 LOCATION '$tblspc_path';
DROP TABLESPACE ts1;
});

my ($end_lsn, $end_walfile) = split /\|/,
  $node->safe_psql('postgres',
	q{SELECT pg_current_wal_insert_lsn(), pg_walfile_name(pg_current_wal_insert_lsn())}
  );

my $default_ts_oid = $node->safe_psql('postgres',
	q{SELECT oid FROM pg_tablespace WHERE spcname = 'pg_default'});
my $postgres_db_oid = $node->safe_psql('postgres',
	q{SELECT oid FROM pg_database WHERE datname = 'postgres'});
my $rel_t1_oid = $node->safe_psql('postgres',
	q{SELECT oid FROM pg_class WHERE relname = 't1'});
my $rel_i1a_oid = $node->safe_psql('postgres',
	q{SELECT oid FROM pg_class WHERE relname = 'i1a'});

$node->stop;


# various ways of specifying WAL range
command_fails_like(
	[ 'pg_tde_waldump', 'foo', 'bar' ],
	qr/error: could not locate WAL file "foo"/,
	'start file not found');
command_like(
	[
		'pg_tde_waldump', '-k',
		$node->data_dir . '/pg_tde',
		$node->data_dir . '/pg_wal/' . $start_walfile
	],
	qr/./,
	'runs with start segment specified');
command_fails_like(
	[
		'pg_tde_waldump', '-k',
		$node->data_dir . '/pg_tde',
		$node->data_dir . '/pg_wal/' . $start_walfile, 'bar'
	],
	qr/error: could not open file "bar"/,
	'end file not found');
command_like(
	[
		'pg_tde_waldump',
		'-k',
		$node->data_dir . '/pg_tde',
		$node->data_dir . '/pg_wal/' . $start_walfile,
		$node->data_dir . '/pg_wal/' . $end_walfile
	],
	qr/./,
	'runs with start and end segment specified');
command_fails_like(
	[
		'pg_tde_waldump', '-p',
		$node->data_dir, '-k',
		$node->data_dir . '/pg_tde'
	],
	qr/error: no start WAL location given/,
	'path option requires start location');
command_like(
	[
		'pg_tde_waldump', '-p',
		$node->data_dir, '--start',
		$start_lsn, '--end',
		$end_lsn, '-k',
		$node->data_dir . '/pg_tde'
	],
	qr/./,
	'runs with path option and start and end locations');
command_fails_like(
	[
		'pg_tde_waldump', '-k',
		$node->data_dir . '/pg_tde', '-p',
		$node->data_dir, '--start',
		$start_lsn
	],
	qr/error: error in WAL record at/,
	'falling off the end of the WAL results in an error');

command_like(
	[
		'pg_tde_waldump', '--quiet', '-k',
		$node->data_dir . '/pg_tde',
		$node->data_dir . '/pg_wal/' . $start_walfile
	],
	qr/^$/,
	'no output with --quiet option');
command_fails_like(
	[
		'pg_tde_waldump', '--quiet', '-k', $node->data_dir . '/pg_tde',
		'-p', $node->data_dir, '--start', $start_lsn
	],
	qr/error: error in WAL record at/,
	'errors are shown with --quiet');


# Test for: Display a message that we're skipping data if `from`
# wasn't a pointer to the start of a record.
{
	# Construct a new LSN that is one byte past the original
	# start_lsn.
	my ($part1, $part2) = split qr{/}, $start_lsn;
	my $lsn2 = hex $part2;
	$lsn2++;
	my $new_start = sprintf("%s/%X", $part1, $lsn2);

	my (@cmd, $stdout, $stderr, $result);

	@cmd = (
		'pg_tde_waldump', '-k', $node->data_dir . '/pg_tde',
		'--start', $new_start, $node->data_dir . '/pg_wal/' . $start_walfile);
	$result = IPC::Run::run \@cmd, '>', \$stdout, '2>', \$stderr;
	ok($result, "runs with start segment and start LSN specified");
	like($stderr, qr/first record is after/, 'info message printed');
}


# Helper function to test various options.  Pass options as arguments.
# Output lines are returned as array.
sub test_pg_waldump
{
	local $Test::Builder::Level = $Test::Builder::Level + 1;
	my @opts = @_;

	my (@cmd, $stdout, $stderr, $result, @lines);

	@cmd = (
		'pg_tde_waldump', '-k',
		$node->data_dir . '/pg_tde', '-p',
		$node->data_dir, '--start',
		$start_lsn, '--end',
		$end_lsn);
	push @cmd, @opts;
	$result = IPC::Run::run \@cmd, '>', \$stdout, '2>', \$stderr;
	ok($result, "pg_waldump @opts: runs ok");
	is($stderr, '', "pg_waldump @opts: no stderr");
	@lines = split /\n/, $stdout;
	ok(@lines > 0, "pg_waldump @opts: some lines are output");
	return @lines;
}

my @lines;

@lines = test_pg_waldump;
is(grep(!/^rmgr: \w/, @lines), 0, 'all output lines are rmgr lines');

@lines = test_pg_waldump('--limit', 6);
is(@lines, 6, 'limit option observed');

@lines = test_pg_waldump('--fullpage');
is(grep(!/^rmgr:.*\bFPW\b/, @lines), 0, 'all output lines are FPW');

@lines = test_pg_waldump('--stats');
like($lines[0], qr/WAL statistics/, "statistics on stdout");
is(grep(/^rmgr:/, @lines), 0, 'no rmgr lines output');

@lines = test_pg_waldump('--stats=record');
like($lines[0], qr/WAL statistics/, "statistics on stdout");
is(grep(/^rmgr:/, @lines), 0, 'no rmgr lines output');

@lines = test_pg_waldump('--rmgr', 'Btree');
is(grep(!/^rmgr: Btree/, @lines), 0, 'only Btree lines');

@lines = test_pg_waldump('--fork', 'init');
is(grep(!/fork init/, @lines), 0, 'only init fork lines');

@lines = test_pg_waldump('--relation',
	"$default_ts_oid/$postgres_db_oid/$rel_t1_oid");
is(grep(!/rel $default_ts_oid\/$postgres_db_oid\/$rel_t1_oid/, @lines),
	0, 'only lines for selected relation');

@lines =
  test_pg_waldump('--relation',
	"$default_ts_oid/$postgres_db_oid/$rel_i1a_oid",
	'--block', 1);
is(grep(!/\bblk 1\b/, @lines), 0, 'only lines for selected block');


done_testing();
