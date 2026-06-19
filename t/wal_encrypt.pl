use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my ($stdout, $stderr);

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->append_conf('postgresql.conf', "wal_level = 'logical'");
# We don't test that it can't start: the test framework doesn't have an easy way to do this
#$node->append_conf('postgresql.conf', "pg_tde.wal_encrypt = 1");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_global_key_provider_file('file-keyring-010', '$keydir/global.keys')
));

(undef, undef, $stderr) =
  $node->psql('postgres', 'SELECT pg_tde_verify_server_key();');
like(
	$stderr,
	qr/ERROR:  principal key not configured for current database/,
	'should not have a valid key');

$stdout = $node->safe_psql('postgres',
	'SELECT key_name, provider_name, provider_id FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'should not show a valid key');

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_global_key_provider('server-key', 'file-keyring-010');
	SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'file-keyring-010');
));

$node->safe_psql('postgres', 'SELECT pg_tde_verify_server_key();');

$stdout = $node->safe_psql('postgres',
	'SELECT key_name, provider_name, provider_id FROM pg_tde_server_key_info();'
);
is($stdout, 'server-key|file-keyring-010|-1', 'should show a valid keys');

$node->safe_psql('postgres', 'ALTER SYSTEM SET pg_tde.wal_encrypt = on;');

$node->restart;

$stdout = $node->safe_psql('postgres', 'SHOW pg_tde.wal_encrypt;');
is($stdout, 'on', 'wal_encrypt should be enabled');

$stdout = $node->safe_psql('postgres',
	"SELECT slot_name FROM pg_create_logical_replication_slot('tde_slot', 'test_decoding');"
);
is($stdout, 'tde_slot', 'should find our replication slot');

$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_wal (id SERIAL, k INTEGER, PRIMARY KEY (id));
	INSERT INTO test_wal (k) VALUES (1), (2);
));

$node->safe_psql('postgres', 'ALTER SYSTEM SET pg_tde.wal_encrypt = off;');

$node->restart;

$stdout = $node->safe_psql('postgres', "SHOW pg_tde.wal_encrypt;");
is($stdout, 'off', 'wal_encrypt should be disabled');

$node->safe_psql('postgres', 'INSERT INTO test_wal (k) VALUES (3), (4);');

$node->safe_psql('postgres', 'ALTER SYSTEM SET pg_tde.wal_encrypt = on;');

$node->restart;

$stdout = $node->safe_psql('postgres', "SHOW pg_tde.wal_encrypt;");
is($stdout, 'on', 'wal_encrypt should be enabled');

$node->safe_psql('postgres', 'INSERT INTO test_wal (k) VALUES (5), (6);');

$node->restart;

$stdout = $node->safe_psql('postgres', "SHOW pg_tde.wal_encrypt;");
is($stdout, 'on', 'wal_encrypt should be enabled');

$node->safe_psql('postgres', 'INSERT INTO test_wal (k) VALUES (7), (8);');

$stdout = $node->safe_psql('postgres',
	"SELECT data FROM pg_logical_slot_get_changes('tde_slot', NULL, NULL, 'include-xids', '0');"
);
is( $stdout, q(BEGIN
COMMIT
BEGIN
table public.test_wal: INSERT: id[integer]:1 k[integer]:1
table public.test_wal: INSERT: id[integer]:2 k[integer]:2
COMMIT
BEGIN
table public.test_wal: INSERT: id[integer]:3 k[integer]:3
table public.test_wal: INSERT: id[integer]:4 k[integer]:4
COMMIT
BEGIN
table public.test_wal: INSERT: id[integer]:5 k[integer]:5
table public.test_wal: INSERT: id[integer]:6 k[integer]:6
COMMIT
BEGIN
table public.test_wal: INSERT: id[integer]:7 k[integer]:7
table public.test_wal: INSERT: id[integer]:8 k[integer]:8
COMMIT), 'should have generated the expected WAL');

$node->safe_psql('postgres', "SELECT pg_drop_replication_slot('tde_slot');");

$node->safe_psql('postgres', 'DROP EXTENSION pg_tde;');

$node->stop;

done_testing();
