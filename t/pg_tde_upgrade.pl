use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

program_help_ok('pg_tde_upgrade');
program_version_ok('pg_tde_upgrade');
program_options_handling_ok('pg_tde_upgrade');

my $oldnotde = PostgreSQL::Test::Cluster->new('oldnotde');
$oldnotde->init;
$oldnotde->start;
$oldnotde->safe_psql(
	'postgres', "
CREATE TABLE test_plain (k int, PRIMARY KEY (k));

INSERT INTO test_plain (k) VALUES (1), (2);
");
$oldnotde->stop;

my $newnotde = PostgreSQL::Test::Cluster->new('newnotde');
$newnotde->init;

command_ok(
	[
		'pg_tde_upgrade', '--no-sync',
		'--old-datadir' => $oldnotde->data_dir,
		'--new-datadir' => $newnotde->data_dir,
		'--old-bindir' => $oldnotde->config_data('--bindir'),
		'--new-bindir' => $newnotde->config_data('--bindir'),
		'--socketdir' => $newnotde->host,
		'--old-port' => $oldnotde->port,
		'--new-port' => $newnotde->port,
	],
	'executes pg_upgrade successfully without pg_tde');

$newnotde->start;
is($newnotde->safe_psql('postgres', "SELECT * FROM test_plain"),
	"1\n2", 'can read tables');
$newnotde->stop;

unlink('/tmp/pg_tde_test_pg_upgrade.per');

my $old = PostgreSQL::Test::Cluster->new('old');
$old->init;
$old->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$old->start;
$old->safe_psql(
	'postgres', "
CREATE EXTENSION pg_tde;

SELECT pg_tde_add_global_key_provider_file('file-vault', '/tmp/pg_tde_test_pg_upgrade.per');
SELECT pg_tde_create_key_using_global_key_provider('server-key', 'file-vault');
SELECT pg_tde_set_key_using_global_key_provider('server-key', 'file-vault');
SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'file-vault');
ALTER SYSTEM SET pg_tde.wal_encrypt = on;

CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap;

INSERT INTO test_enc (k) VALUES (1), (2);
");
$old->restart;
$old->stop;

my $new = PostgreSQL::Test::Cluster->new('new');
$new->init;
$new->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$new->append_conf('postgresql.conf', "pg_tde.wal_encrypt = on");

command_ok(
	[
		'pg_tde_upgrade', '--no-sync',
		'--old-datadir' => $old->data_dir,
		'--new-datadir' => $new->data_dir,
		'--old-bindir' => $old->config_data('--bindir'),
		'--new-bindir' => $new->config_data('--bindir'),
		'--socketdir' => $new->host,
		'--old-port' => $old->port,
		'--new-port' => $new->port,
	],
	'executes pg_upgrade successfully with pg_tde');

$new->start;
is($new->safe_psql('postgres', "SELECT * FROM test_enc"),
	"1\n2", 'can read encrypted tables');
$new->stop;

done_testing();
