use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::RecursiveCopy;
use PostgreSQL::Test::Utils;
use Test::More;

# With small segments and WAL flushed in large chunks the walsender sends
# messages which span segment boundaries. Check that WAL encrypted by
# pg_tde_basebackup is still readable.

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init(allows_streaming => 1, extra => ['--wal-segsize=1']);
$node->append_conf(
	'postgresql.conf', q{
shared_preload_libraries = 'pg_tde'
wal_buffers = 32MB
wal_writer_delay = 10s
checkpoint_timeout = 1h
max_wal_size = 1GB
});
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_global_key_provider_file('global-provider', '$keydir/global.keys');
	SELECT pg_tde_create_key_using_global_key_provider('server-key', 'global-provider');
	SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'global-provider');
	ALTER SYSTEM SET pg_tde.wal_encrypt = on;
));
$node->restart;

$node->safe_psql('postgres', 'CREATE TABLE t (x int, pad text);');

my $backup_dir = $node->backup_dir . '/backup';
mkdir $backup_dir or die "mkdir($backup_dir) failed: $!";
PostgreSQL::Test::RecursiveCopy::copypath($node->data_dir . '/pg_tde',
	$backup_dir . '/pg_tde');

my ($stdout, $stderr) = ('', '');
my $h = IPC::Run::start(
	[
		'pg_tde_basebackup', '-D',
		$backup_dir, '-h',
		$node->host, '-p',
		$node->port, '-c',
		'fast', '--no-sync',
		'-E', '-X',
		'stream', '--max-rate',
		'4M'
	],
	'>' => \$stdout,
	'2>' => \$stderr);

$node->poll_query_until('postgres',
	"SELECT count(*) > 0 FROM pg_stat_replication WHERE state = 'streaming'")
  or die "WAL streaming did not start";

for my $i (1 .. 5)
{
	$node->safe_psql('postgres',
		"INSERT INTO t SELECT g, repeat('x', 100) FROM generate_series(1, 20000) g;"
	);
}
my $expected = $node->safe_psql('postgres', 'SELECT count(*) FROM t;');

my $running = $node->safe_psql('postgres',
	'SELECT count(*) FROM pg_stat_progress_basebackup;');
is($running, '1', 'base backup still running after WAL was generated');

$h->finish;
is($h->result(0), 0, 'pg_tde_basebackup succeeded')
  or diag("stderr: $stderr");

my $restored = PostgreSQL::Test::Cluster->new('restored');
$restored->init_from_backup($node, 'backup');
$restored->start;

is($restored->safe_psql('postgres', 'SELECT count(*) FROM t;'),
	$expected, 'restored backup has all rows');

$restored->stop;
$node->stop;

done_testing();
