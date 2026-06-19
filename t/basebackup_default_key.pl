# Tests that pg_tde_basebackup -E works after setting just a default
# principal key, without first restarting the primary. Before the fix,
# the server (WAL) principal key was only materialized lazily on the
# next server start, so taking an encrypted-WAL base backup of a freshly
# configured cluster would fail with "could not find server principal key".

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::RecursiveCopy;
use PostgreSQL::Test::Utils;
use Test::More;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $primary = PostgreSQL::Test::Cluster->new('primary');
$primary->init(allows_streaming => 1);
$primary->append_conf('postgresql.conf',
	"shared_preload_libraries = 'pg_tde'");
$primary->start;

$primary->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');
$primary->safe_psql('postgres',
	"SELECT pg_tde_add_global_key_provider_file('file-provider','$keydir/global.keys');"
);
$primary->safe_psql('postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('key1','file-provider');"
);
$primary->safe_psql('postgres',
	"SELECT pg_tde_set_default_key_using_global_key_provider('key1','file-provider');"
);

my $server_key = $primary->safe_psql('postgres',
	'SELECT key_name FROM pg_tde_server_key_info();');
is($server_key, 'key1',
	'server principal key auto-configured when default key is set');

my $tempdir = PostgreSQL::Test::Utils::tempdir;
my $backup_dir = "$tempdir/backup";

mkdir $backup_dir or die "mkdir $backup_dir failed: $!";
PostgreSQL::Test::RecursiveCopy::copypath($primary->data_dir . '/pg_tde',
	$backup_dir . '/pg_tde');

$primary->command_ok(
	[
		'pg_tde_basebackup', '-D',
		$backup_dir, '-h',
		$primary->host, '-p',
		$primary->port, '--checkpoint',
		'fast', '--no-sync',
		'-E', '-X',
		'stream',
	],
	'pg_tde_basebackup -E succeeds after only setting default key');

$primary->stop;

done_testing();
