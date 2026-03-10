use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

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

CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap;

INSERT INTO test_enc (k) VALUES (1), (2);
");
$old->stop;

my $new = PostgreSQL::Test::Cluster->new('new');
$new->init;
$new->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");

system_or_bail(
	'cp', '-R',
	$old->data_dir . '/pg_tde',
	$new->data_dir . '/pg_tde');

command_ok(
	[
		'pg_upgrade', '--no-sync',
		'--old-datadir' => $old->data_dir,
		'--new-datadir' => $new->data_dir,
		'--old-bindir' => $old->config_data('--bindir'),
		'--new-bindir' => $new->config_data('--bindir'),
		'--socketdir' => $new->host,
		'--old-port' => $old->port,
		'--new-port' => $new->port,
	],
	'executes pg_upgrade successfully');

$new->start;
is($new->safe_psql('postgres', "SELECT * FROM test_enc"),
	"1\n2", 'can read encrypted tables');
$new->stop;

done_testing();
