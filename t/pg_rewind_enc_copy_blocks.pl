# Tests the scenario when only changed blocks of the encrypted relation are
# copied from the source, hence mixes data encrypted with different keys. So
# we check if pg_tde_rewind handles that properly, and the data is re-encrypted
# correctly.
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

	$cluster_name = $cluster_name . $extra_name if defined $extra_name;

	RewindTest::setup_cluster($cluster_name, [], $extra_conf);
	RewindTest::start_primary();
	RewindTest::create_standby($cluster_name);

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

	RewindTest::promote_standby();

	# Makes pg_rewind to copy some blocks of the relation
	# (mixing data encrypted with different keys on the target).
	primary_psql("UPDATE block_t SET f1='YYYYYYY' WHERE id % 10 = 0;");

	# Insert some data making rewind to copy the tail of this relation
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
