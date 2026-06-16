# Triggers a blocks re-encryption of the segmented relation to test fix for
# PG-2407 case 1
#
use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Utils;
use Test::More;

use FindBin;
use lib $FindBin::RealBin;

use RewindTest;

my $test_mode = 'local';

RewindTest::setup_cluster($test_mode, [],
	[ 'wal_keep_size=4GB', 'max_wal_size=4GB' ]);
RewindTest::start_primary();

RewindTest::create_standby($test_mode);

# Create a segmented relation (size > 1Gb)
primary_psql("
	CREATE TABLE t1 (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap;
	INSERT INTO t1 (f1) SELECT repeat(md5(g::text), 60) FROM generate_series(1, 600_000) g;
");
primary_psql("CHECKPOINT");

# Crosscheck that the relation is segmented
my $fpath =
  $node_primary->safe_psql('postgres', "SELECT pg_relation_filepath('t1')");
ok(-e $node_primary->data_dir . "/$fpath.1",
	'segmented relation file exists');

RewindTest::promote_standby();

# # Makes pg_rewind to copy some blocks of the relation
# # from both segments
primary_psql("UPDATE t1 SET f1='YYYYYYY' WHERE id % 1000 = 0;");

RewindTest::run_pg_rewind($test_mode);

check_query(
	'SELECT count(*) FROM t1',
	qq(600000
),
	'tail-copy');

RewindTest::clean_rewind_test();


done_testing();
