use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->append_conf('postgresql.conf', "deadlock_timeout = 10ms");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-key', 'file-vault');
));

# Runs ATTACH PARTITION while another session holds the locks taken by
# $setup, then runs $then in that session while ATTACH PARTITION waits.
sub attach_while_locked
{
	my ($name, $setup, $attach, $then) = @_;

	$node->safe_psql(
		'postgres', q(
		DROP TABLE IF EXISTS parted, t_a, t_b;
		CREATE TABLE parted (a int) PARTITION BY RANGE (a);
		CREATE INDEX parted_idx ON parted (a);
		CREATE TABLE p_plain PARTITION OF parted FOR VALUES FROM (0) TO (10) USING heap;
		CREATE TABLE p_def PARTITION OF parted DEFAULT USING heap;
		CREATE TABLE t_a (a int) USING tde_heap;
	));

	my $locker = $node->background_psql('postgres', on_error_stop => 0);
	my $attacher = $node->background_psql('postgres', on_error_stop => 0);

	$locker->query_safe("BEGIN; $setup");
	$attacher->query_until(qr/start/, "\\echo start\n$attach;\n");
	$node->poll_query_until(
		'postgres', q(
		SELECT EXISTS (SELECT FROM pg_stat_activity
			WHERE wait_event_type = 'Lock'
			AND query LIKE 'ALTER TABLE parted ATTACH%');
	));

	if ($then)
	{
		my (undef, $err) = $locker->query($then);
		is($err, 0, "$name: other session is not blocked");
	}
	$locker->query('COMMIT');

	my (undef, $err) = $attacher->query('');
	is($err, 0, "$name: ATTACH PARTITION succeeds");

	$locker->quit;
	$attacher->quit;
}

attach_while_locked(
	'parent locked',
	'LOCK parted IN SHARE MODE;',
	'ALTER TABLE parted ATTACH PARTITION t_a FOR VALUES FROM (10) TO (20)',
	'SELECT FROM t_a;');

attach_while_locked(
	'default partition locked',
	'SELECT FROM p_def;',
	'ALTER TABLE parted ATTACH PARTITION t_a FOR VALUES FROM (10) TO (20)',
	'SELECT FROM t_a;');

# The attached table is created while ATTACH PARTITION already runs
attach_while_locked(
	'parent locked, concurrent create',
	'LOCK parted IN SHARE MODE; CREATE TABLE t_b (a int) USING tde_heap;',
	'ALTER TABLE parted ATTACH PARTITION t_b FOR VALUES FROM (10) TO (20)');
is( $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('t_b_a_idx');"),
	't',
	'parent locked, concurrent create: index is encrypted');

attach_while_locked(
	'default partition locked, concurrent create',
	'CREATE TABLE t_b (a int) USING tde_heap; SELECT FROM p_def;',
	'ALTER TABLE parted ATTACH PARTITION t_b FOR VALUES FROM (10) TO (20)');
is( $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('t_b_a_idx');"),
	't',
	'default partition locked, concurrent create: index is encrypted');

$node->stop;

done_testing();
