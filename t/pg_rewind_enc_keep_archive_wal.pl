# Make pg_rewind to restore some target's WAL segments from the archive and then
# use some of those segments for the rewinded recovery.
# The test checks if such segments are properly re-encrypted, hence no
# "invalid magic number" in server log during recovery after the rewind.
#
use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Utils;
use Test::More;
use File::Copy;

use FindBin;
use lib $FindBin::RealBin;

use RewindTest;

sub wait_for_archive
{
	my $archive_dir = shift;
	my $node = shift;

	my $wal = $node->safe_psql('postgres',
		"SELECT pg_walfile_name(pg_current_wal_lsn())");
	$wal =~ s/\s+//g;

	print "Waiting for WAL archive: $wal\n";

	my $timeout = 180;
	while ($timeout > 0)
	{
		if (-f "$archive_dir/$wal")
		{
			print "WAL archived: $wal\n";
			return 1;
		}

		sleep 1;
		$timeout--;
	}

	print "WAL not archived: $wal\n";
	return 0;
}

my $extra_conf;
my $cluster_name = 'local';

my $tempdir = PostgreSQL::Test::Utils::tempdir_short();

my $archive_dir = $tempdir . '/archive';


mkdir($archive_dir) || die "mkdir $archive_dir: $!";

push @$extra_conf, "wal_keep_size=0";
push @$extra_conf, "archive_mode=on";
push @$extra_conf, "archive_timeout=10s";
push @$extra_conf,
  "archive_command='pg_tde_archive_decrypt %f %p \"cp %%p $archive_dir/%%f\"'";
push @$extra_conf,
  "restore_command='pg_tde_restore_encrypt %f %p \"cp $archive_dir/%%f %%p\"'";

RewindTest::setup_cluster($cluster_name, [], $extra_conf);
RewindTest::start_primary();

my $node_primary = $RewindTest::node_primary;

primary_psql("
	CREATE TABLE t1(id int) USING tde_heap;
	INSERT INTO t1 SELECT generate_series(1,10000);
");

primary_psql("CHECKPOINT");

primary_psql("SELECT pg_switch_wal();");
primary_psql("CHECKPOINT");
wait_for_archive($archive_dir, $node_primary);

RewindTest::create_standby($cluster_name);

my $node_standby = $RewindTest::node_standby;

primary_psql("SELECT pg_switch_wal();");
primary_psql("CHECKPOINT");
wait_for_archive($archive_dir, $node_primary);

RewindTest::promote_standby();


standby_psql("INSERT INTO t1 VALUES (999999)");
standby_psql("SELECT pg_switch_wal()");
standby_psql("CHECKPOINT");
wait_for_archive($archive_dir, $node_standby);


my $newkey = "key_after_promotion";
standby_psql(
	"SELECT pg_tde_create_key_using_global_key_provider('$newkey', 'file-keyring-wal')"
);
standby_psql(
	"SELECT pg_tde_set_key_using_global_key_provider('$newkey', 'file-keyring-wal')"
);
standby_psql("SELECT pg_switch_wal();");


standby_psql("
	CREATE TABLE target_only(id int) USING tde_heap;
	INSERT INTO target_only VALUES (1),(2);
");

primary_psql("
	CREATE TABLE source_only(id int) USING tde_heap;
	INSERT INTO source_only VALUES (10),(20);
");

primary_psql("SELECT pg_switch_wal();");
primary_psql("CHECKPOINT");
wait_for_archive($archive_dir, $node_primary);

standby_psql("SELECT pg_switch_wal();");
standby_psql("CHECKPOINT");
wait_for_archive($archive_dir, $node_standby);

$node_primary->stop;

my $primary_pgdata = $node_primary->data_dir;
my $standby_pgdata = $node_standby->data_dir;

copy(
	"$primary_pgdata/postgresql.conf",
	"$tempdir/primary-postgresql.conf.tmp");

$node_standby->stop;
command_ok(
	[
		'pg_tde_rewind',
		"--debug",
		"--source-pgdata=$standby_pgdata",
		"--target-pgdata=$primary_pgdata",
		"--restore-target-wal",
		"--config-file",
		"$tempdir/primary-postgresql.conf.tmp"
	],
	'pg_rewind local');

move(
	"$tempdir/primary-postgresql.conf.tmp",
	"$primary_pgdata/postgresql.conf");


$node_primary->start;


ok(!$RewindTest::node_primary->log_contains('invalid magic number'),
	'verify there are no "invalid magic number"');

RewindTest::clean_rewind_test();


done_testing();
