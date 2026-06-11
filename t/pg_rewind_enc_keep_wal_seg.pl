# Make pg_rewind keep some WAL segments on the target and use archive
# restore_command to generate new WAL keys while creating the replica.
# The kept WAL segments should then be re-encrypted by pg_rewind.
#
use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Utils;
use Test::More;

use FindBin;
use lib $FindBin::RealBin;

use RewindTest;

sub run_test
{
	my $test_mode = shift;
	my $extra_name = shift;
	my $extra_conf = shift;

	my $cluster_name = $test_mode;

	my $tempdir = PostgreSQL::Test::Utils::tempdir_short();

	my $archive_dir = $tempdir . '/archive';

	$cluster_name = $cluster_name . $extra_name if defined $extra_name;

	mkdir($archive_dir) || die "mkdir $archive_dir: $!";

	push @$extra_conf, "wal_level=replica";
	push @$extra_conf, "archive_mode=on";
	push @$extra_conf,
	  "archive_command='pg_tde_archive_decrypt %f %p \"cp %%p $archive_dir/%%f\"'";
	push @$extra_conf,
	  "restore_command='pg_tde_restore_encrypt %f %p \"cp $archive_dir/%%f %%p\"'";

	RewindTest::setup_cluster($cluster_name, [], $extra_conf);
	RewindTest::start_primary();

	$RewindTest::node_primary->stop;
	$RewindTest::node_primary->start;

	primary_psql(
		"CREATE TABLE tail_t (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap"
	);
	primary_psql(
		"INSERT INTO tail_t (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)"
	);
	primary_psql(
		"CREATE TABLE block_t (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap"
	);
	primary_psql(
		"INSERT INTO block_t (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)"
	);
	primary_psql("CHECKPOINT");

	RewindTest::create_standby($cluster_name);

	RewindTest::promote_standby();

	# Makes pg_rewind copy some blocks of the relation
	# (mixing data encrypted with different keys on the target).
	primary_psql("UPDATE block_t SET f1='YYYYYYY' WHERE id % 10 = 0;");

	# Insert some data making rewind copy the tail of this relation
	# (mixing data encrypted with different keys on the target).
	standby_psql(
		"INSERT INTO tail_t (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)"
	);
	standby_psql("CHECKPOINT");


	RewindTest::run_pg_rewind($test_mode);

	check_query(
		'SELECT count(*) FROM tail_t',
		qq(2000
),
		'tail-copy');

	check_query(
		'SELECT count(*) FROM block_t',
		qq(1000
),
		'blocks-copy');

	RewindTest::clean_rewind_test();
	return;
}

# Run the test in all source modes plus local aes_256
run_test('local');
run_test('remote');
run_test('archive');

my @conf_params = ("pg_tde.cipher = 'aes_256'");
run_test('local', "_aes_256", \@conf_params);

done_testing();
