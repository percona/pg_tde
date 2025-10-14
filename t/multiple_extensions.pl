#!/usr/bin/perl

use strict;
use warnings;
use File::Basename;
use Test::More;
use lib 't';
use pgtde;

PGTDE::setup_files_dir(basename($0));

my $PG_VERSION_STRING = `pg_config --version`;

if (index(lc($PG_VERSION_STRING), lc("Percona Distribution")) == -1)
{
	plan skip_all =>
	  "pg_tde test case only for PPG server package install with extensions.";
}

unlink('/tmp/keyring_data_file');

open my $conf2, '>>', "/tmp/datafile-location";
print $conf2 "/tmp/keyring_data_file\n";
close $conf2;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf',
	"shared_preload_libraries = 'pg_tde, pg_stat_monitor, pgaudit, set_user, pg_repack'"
);
if ($node->pg_version >= 18)
{
	$node->append_conf('postgresql.conf', 'io_method = sync');
}
$node->append_conf('postgresql.conf',
	"pg_stat_monitor.pgsm_bucket_time = 360000");
$node->append_conf('postgresql.conf',
	"pg_stat_monitor.pgsm_normalized_query = 'yes'");
$node->start;

# Create PGSM extension
my ($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS pg_stat_monitor;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE PGSM EXTENSION");
PGTDE::append_to_debug_file($stdout);

($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'SELECT pg_stat_monitor_reset();',
	extra_params => [ '-a', '-Pformat=aligned', '-Ptuples_only=off' ]);
ok($cmdret == 0, "Reset PGSM EXTENSION");
PGTDE::append_to_debug_file($stdout);

# Create pg_tde extension
($cmdret, $stdout, $stderr) =
  $node->psql('postgres', 'CREATE EXTENSION pg_tde;', extra_params => ['-a']);
ok($cmdret == 0, "CREATE PGTDE EXTENSION");
PGTDE::append_to_result_file($stdout);

# Create Other extensions
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS pgaudit;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE pgaudit EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS set_user;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE set_user EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS pg_repack;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE pg_repack EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	"SET pgaudit.log = 'none'; CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS postgis; SET pgaudit.log = 'all';",
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE postgis EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS postgis_raster;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE postgis_raster EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS postgis_sfcgal;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE postgis_sfcgal EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS fuzzystrmatch;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE fuzzystrmatch EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS address_standardizer;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE address_standardizer EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS address_standardizer_data_us;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE address_standardizer_data_us EXTENSION");
PGTDE::append_to_debug_file($stdout);
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'CREATE EXTENSION IF NOT EXISTS IF NOT EXISTS postgis_tiger_geocoder;',
	extra_params => ['-a']);
ok($cmdret == 0, "CREATE postgis_tiger_geocoder EXTENSION");
PGTDE::append_to_debug_file($stdout);

$node->psql(
	'postgres',
	"SELECT pg_tde_add_database_key_provider_file('file-provider', json_object('type' VALUE 'file', 'path' VALUE '/tmp/datafile-location'));",
	extra_params => ['-a']);
$node->psql(
	'postgres',
	"SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-provider');",
	extra_params => ['-a']);
$node->psql(
	'postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-provider');",
	extra_params => ['-a']);

$stdout = $node->safe_psql(
	'postgres',
	'CREATE TABLE test_enc1 (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap;',
	extra_params => ['-a']);
PGTDE::append_to_result_file($stdout);

$stdout = $node->safe_psql(
	'postgres',
	'INSERT INTO test_enc1 (k) VALUES (5), (6);',
	extra_params => ['-a']);
PGTDE::append_to_result_file($stdout);

$stdout = $node->safe_psql(
	'postgres',
	'SELECT * FROM test_enc1 ORDER BY id;',
	extra_params => ['-a']);
PGTDE::append_to_result_file($stdout);

PGTDE::append_to_result_file("-- server restart");
$node->restart;

$stdout = $node->safe_psql(
	'postgres',
	'SELECT * FROM test_enc1 ORDER BY id;',
	extra_params => ['-a']);
PGTDE::append_to_result_file($stdout);

$stdout = $node->safe_psql(
	'postgres',
	'DROP TABLE test_enc1;',
	extra_params => ['-a']);
PGTDE::append_to_result_file($stdout);

# Print PGSM settings
($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	"SELECT name, setting, unit, context, vartype, source, min_val, max_val, enumvals, boot_val, reset_val, pending_restart FROM pg_settings WHERE name = 'pg_stat_monitor.pgsm_query_shared_buffer';",
	extra_params => [ '-a', '-Pformat=aligned', '-Ptuples_only=off' ]);
ok($cmdret == 0, "Print PGTDE EXTENSION Settings");
PGTDE::append_to_debug_file($stdout);

# Create example database and run pgbench init
($cmdret, $stdout, $stderr) =
  $node->psql('postgres', 'CREATE database example;', extra_params => ['-a']);
print "cmdret $cmdret\n";
ok($cmdret == 0, "CREATE Database example");
PGTDE::append_to_debug_file($stdout);

my $port = $node->port;
print "port $port \n";

my $out = system("pgbench -i -s 20 -p $port example");
print " out: $out \n";
ok($cmdret == 0, "Perform pgbench init");

$out = system("pgbench -c 10 -j 2 -t 5000 -p $port example");
print " out: $out \n";
ok($cmdret == 0, "Run pgbench");

($cmdret, $stdout, $stderr) = $node->psql(
	'postgres',
	'SELECT datname, substr(query, 0, 150) AS query, SUM(calls) AS calls FROM pg_stat_monitor GROUP BY datname, query ORDER BY datname, query, calls;',
	extra_params => [ '-a', '-Pformat=aligned', '-Ptuples_only=off' ]);
ok($cmdret == 0, "SELECT XXX FROM pg_stat_monitor");
PGTDE::append_to_debug_file($stdout);

$stdout = $node->safe_psql(
	'postgres',
	'DROP EXTENSION pg_tde;',
	extra_params => ['-a']);
ok($cmdret == 0, "DROP PGTDE EXTENSION");
PGTDE::append_to_result_file($stdout);

$stdout = $node->safe_psql(
	'postgres',
	'DROP EXTENSION pg_stat_monitor;',
	extra_params => ['-a']);
ok($cmdret == 0, "DROP PGTDE EXTENSION");
PGTDE::append_to_debug_file($stdout);

$node->stop;

# Compare the expected and out file
my $compare = PGTDE->compare_results();

is($compare, 0,
	"Compare Files: $PGTDE::expected_filename_with_path and $PGTDE::out_filename_with_path files."
);

done_testing();
