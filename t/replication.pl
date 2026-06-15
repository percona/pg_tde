use strict;
use warnings FATAL => 'all';
use pgtde;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $stdout;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $primary = PostgreSQL::Test::Cluster->new('primary');
$primary->init(allows_streaming => 1);
$primary->append_conf(
	'postgresql.conf', q{
checkpoint_timeout = 1h
shared_preload_libraries = 'pg_tde'
});
$primary->start;

$primary->backup('backup');
my $replica = PostgreSQL::Test::Cluster->new('replica');
$replica->init_from_backup($primary, 'backup', has_streaming => 1);
$replica->set_standby_mode();
$replica->start;

$primary->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-key', 'file-vault');

	CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc (x) VALUES (1), (2);

	CREATE TABLE test_plain (x int PRIMARY KEY) USING heap;
	INSERT INTO test_plain (x) VALUES (3), (4);
));

$primary->wait_for_catchup('replica');

$stdout =
  $replica->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'test_enc is encrypted on the replica');
$stdout = $replica->safe_psql('postgres',
	"SELECT pg_tde_is_encrypted('test_enc_pkey');");
is($stdout, 't', 'test_enc_pkey is encrypted on the replica');
$stdout =
  $replica->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY x;');
is($stdout, "1\n2", 'can read from test_enc on the replica');

$stdout = $replica->safe_psql('postgres',
	"SELECT pg_tde_is_encrypted('test_plain');");
is($stdout, 'f', 'test_plain is not encrypted on the replica');
$stdout = $replica->safe_psql('postgres',
	"SELECT pg_tde_is_encrypted('test_plain_pkey');");
is($stdout, 'f', 'test_plain_pkey is not encrypted on the replica');
$stdout =
  $replica->safe_psql('postgres', 'SELECT * FROM test_plain ORDER BY x;');
is($stdout, "3\n4", 'can read from test_plain on the replica');

# check primary crash with WAL encryption
#
# TODO: This does not seem to actually test WAL encryption
$primary->safe_psql(
	'postgres', qq(
	SELECT pg_tde_add_global_key_provider_file('file-vault', '$keydir/global.key');
	SELECT pg_tde_create_key_using_global_key_provider('test-global-key', 'file-vault');
	SELECT pg_tde_set_server_key_using_global_key_provider('test-global-key', 'file-vault');

	CREATE TABLE test_enc2 (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc2 (x) VALUES (1), (2);

	ALTER SYSTEM SET pg_tde.wal_encrypt = 'on';
));

$primary->kill9;

PGTDE::poll_start($primary);
$primary->wait_for_catchup('replica');

$stdout =
  $replica->safe_psql('postgres', 'SELECT * FROM test_enc2 ORDER BY x;');
is($stdout, "1\n2", 'can read from test_enc2');

$replica->stop;
$primary->stop;

done_testing();
