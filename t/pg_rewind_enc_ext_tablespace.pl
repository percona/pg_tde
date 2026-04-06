# Check encrypted relations in external tablespaces
#
use strict;
use warnings FATAL => 'all';
use File::Path qw(rmtree make_path);
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

	my $primary_tblspc = $tempdir . 'tblsp_primary';
	my $primary_tblspc_bcp = $tempdir . 'tblsp_primary_bcp';
	my $standby_tblspc = $tempdir . 'tblsp_standby';

	$cluster_name = $cluster_name . $extra_name if defined $extra_name;

	mkdir($primary_tblspc) || die "mkdir $primary_tblspc: $!";

	RewindTest::setup_cluster($cluster_name, [], $extra_conf);
	RewindTest::start_primary();

	primary_psql("CREATE TABLESPACE ts1 LOCATION '$primary_tblspc'");

	my $ts1_oid = $RewindTest::node_primary->safe_psql('postgres',
		"SELECT oid FROM pg_tablespace WHERE spcname = 'ts1'");
	chomp $ts1_oid;

	RewindTest::create_standby(
		$cluster_name,
		backup_options =>
		  [ '--tablespace-mapping', "$primary_tblspc=$primary_tblspc_bcp" ],
		tablespace_map => { $ts1_oid => $standby_tblspc });

	primary_psql(
		"CREATE TABLE tail_t (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap TABLESPACE ts1"
	);
	primary_psql(
		"INSERT INTO tail_t (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)"
	);
	primary_psql(
		"CREATE TABLE block_t (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap TABLESPACE ts1"
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
