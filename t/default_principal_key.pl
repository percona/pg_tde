use strict;
use warnings;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my ($stdout, $stderr);

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_global_key_provider_file('file-provider', '$keydir/global.keys');
));

(undef, undef, $stderr) =
  $node->psql('postgres', 'SELECT pg_tde_verify_default_key();');
like(
	$stderr,
	qr/ERROR:  principal key not configured for current database/,
	'fails due to no default principal key');

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_default_key_info();'
);
is($stdout, '||', 'lists no default principal key');

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_global_key_provider('default-key', 'file-provider');
	SELECT pg_tde_set_default_key_using_global_key_provider('default-key', 'file-provider');
));

$stdout = $node->safe_psql('postgres', 'SELECT pg_tde_verify_default_key();');
is($stdout, '', 'verification succeeds now that we have a key');

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_default_key_info();'
);
is( $stdout,
	'-1|file-provider|default-key',
	'lists the new default principal key');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_delete_global_key_provider('file-provider');");
like(
	$stderr,
	qr/ERROR:  cannot delete provider which is currently in use/,
	'refuses to delete provider with global keys in');

$stdout = $node->safe_psql('postgres',
	'SELECT id, name FROM pg_tde_list_all_global_key_providers();');
is($stdout, '-1|file-provider',
	'key provider is still there after failed delete');

# Test key roatation

$node->safe_psql('postgres', 'CREATE DATABASE other');
$node->safe_psql('other', 'CREATE EXTENSION pg_tde;');

# Database: postgres
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '||', 'default key has not been localized yet in postgres');
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc (x) VALUES (1), (2);
));
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is( $stdout,
	'-1|file-provider|default-key',
	'default key is now localized in postgres');

# Database: other
$stdout = $node->safe_psql('other',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '||', 'default key has not been localized yet in other');
$node->safe_psql(
	'other', qq(
	CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc (x) VALUES (1), (2);
));
$stdout = $node->safe_psql('other',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is( $stdout,
	'-1|file-provider|default-key',
	'default key is now localized in other');

# Rotate default key which affects all databases
$node->safe_psql(
	'postgres', qq(
	CHECKPOINT;
	SELECT pg_tde_create_key_using_global_key_provider('new-default-key', 'file-provider');
	SELECT pg_tde_set_default_key_using_global_key_provider('new-default-key', 'file-provider');
));

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is( $stdout,
	'-1|file-provider|new-default-key',
	'default key is now localized in postgres');
$stdout = $node->safe_psql('other',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is( $stdout,
	'-1|file-provider|new-default-key',
	'default key is now localized in other');

$node->restart;

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY x;');
is($stdout, "1\n2", 'can still read data after restart in postgres');
$stdout = $node->safe_psql('other', 'SELECT * FROM test_enc ORDER BY x;');
is($stdout, "1\n2", 'can still read data after restart in other');

# Test dropping default keys

$node->safe_psql('other', 'DROP TABLE test_enc;');

(undef, undef, $stderr) =
  $node->psql('other', 'SELECT pg_tde_delete_default_key();');
like(
	$stderr,
	qr/ERROR:  cannot delete default principal key\nHINT:  There are encrypted tables in the database with id: 5/,
	'cannot drop default key when people are using it');

$node->safe_psql('postgres', 'DROP TABLE test_enc;');

$stdout = $node->safe_psql('other', 'SELECT pg_tde_delete_default_key();');
is($stdout, '', 'can delete default key when nobody uses it');

$stdout = $node->safe_psql('postgres',
	"SELECT pg_tde_delete_global_key_provider('file-provider')");
is($stdout, '', 'can delete key provider after the key has been deleted');

done_testing();
