
# Copyright (c) 2021-2024, PostgreSQL Global Development Group

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
		"CREATE TABLE tbl1 (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap"
	);
	primary_psql(
		"INSERT INTO tbl1 (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)"
	);
	primary_psql("CHECKPOINT");

	RewindTest::promote_standby();

	# Trigger updated blocks in FSM
	standby_psql("DELETE FROM tbl1 WHERE id % 15 = 0;");
	standby_psql(
		"INSERT INTO tbl1 (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)"
	);


	RewindTest::run_pg_rewind($test_mode);

	ok(!$RewindTest::node_primary->log_contains('; zeroing out page'),
		'verify there are no corrupted _fsm relations');

	check_query(
		'SELECT count(*) FROM tbl1',
		qq(1934
),
		'check table');

	RewindTest::clean_rewind_test();
	return;
}

# Run the test in both modes
run_test('local');
run_test('remote');
run_test('archive');

my @conf_params = ("pg_tde.cipher = 'aes_256'");
run_test('local', "_aes_256", \@conf_params);

done_testing();
