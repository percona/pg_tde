use strict;
use warnings FATAL => 'all';
use pgtde;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $primary = PostgreSQL::Test::Cluster->new('primary');
$primary->init(allows_streaming => 1);
$primary->append_conf('postgresql.conf',
	"shared_preload_libraries = 'pg_tde'");
# Fits a whole segment, so a segment switch is written in one go
$primary->append_conf('postgresql.conf', "wal_buffers = 16MB");
$primary->start;

if ($primary->safe_psql('postgres',
		"SELECT count(*) FROM pg_available_extensions WHERE name = 'injection_points';"
	) eq '0')
{
	plan skip_all => 'Extension injection_points not installed';
}

$primary->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	CREATE EXTENSION injection_points;
	SELECT pg_tde_add_global_key_provider_file('file-keyring', '$keydir/global.keys');
	SELECT pg_tde_create_key_using_global_key_provider('server-key', 'file-keyring');
	SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'file-keyring');
	ALTER SYSTEM SET pg_tde.wal_encrypt = on;
));
$primary->restart;

PGTDE::backup($primary, 'backup');
my $standby = PostgreSQL::Test::Cluster->new('standby');
$standby->init_from_backup($primary, 'backup', has_streaming => 1);
$standby->start;

# A restart creates a new WAL range which starts at the first WAL written after
# the restart. That WAL shares a page with WAL written before the restart. Make
# a walsender read that page before the restart's first write and decrypt it
# after.
sub test_range_change
{
	my ($wal_encrypt) = @_;

	# Make the shutdown checkpoint the first record on the first page of a
	# segment, which is where the standby will restart streaming from.
	$primary->safe_psql('postgres', 'SELECT pg_switch_wal();');
	$primary->wait_for_catchup($standby);
	$standby->stop;

	$primary->safe_psql('postgres',
		"ALTER SYSTEM SET pg_tde.wal_encrypt = $wal_encrypt;");
	$primary->restart;

	$primary->safe_psql('postgres',
		"SELECT injection_points_attach('pg-tde-xlog-seg-read-before-decrypt', 'wait');"
	);

	$standby->start;
	$primary->wait_for_event('walsender',
		'pg-tde-xlog-seg-read-before-decrypt');

	$primary->safe_psql('postgres',
		"CREATE TABLE test_$wal_encrypt AS SELECT generate_series(1, 10) AS a;"
	);

	$primary->safe_psql(
		'postgres', q(
		SELECT injection_points_detach('pg-tde-xlog-seg-read-before-decrypt');
		SELECT injection_points_wakeup('pg-tde-xlog-seg-read-before-decrypt');
	));

	$primary->wait_for_catchup($standby);

	my $count = $standby->safe_psql('postgres',
		"SELECT count(*) FROM test_$wal_encrypt;");
	is($count, '10',
		"standby replays WAL across restart with wal_encrypt = $wal_encrypt");
}

test_range_change('on');
test_range_change('off');

# The first write after a restart starts the new WAL range. Make it a segment
# switch, which ends at a page boundary.
$primary->safe_psql('postgres', "ALTER SYSTEM SET pg_tde.wal_encrypt = on;");
$primary->restart;
$primary->safe_psql('postgres', 'SELECT pg_switch_wal();');
$primary->safe_psql('postgres',
	'CREATE TABLE test_switch AS SELECT generate_series(1, 10) AS a;');
$primary->wait_for_catchup($standby);
is($standby->safe_psql('postgres', 'SELECT count(*) FROM test_switch;'),
	'10', 'segment switch as first write after restart');

$standby->stop;
$primary->stop;

done_testing();
