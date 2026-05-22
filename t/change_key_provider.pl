#!/usr/bin/perl

use strict;
use warnings;
use File::Copy;
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

	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db1.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-key', 'file-vault');
));

$stdout = $node->safe_psql('postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");
is( $stdout,
	qq(1|file-vault|file|{"path" : "$keydir/db1.keys"}),
	'can list providers');

$node->safe_psql(
	'postgres', q(
	CREATE TABLE test_enc (id serial, k integer, PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc (k) VALUES (5), (6);
));

$node->safe_psql('postgres', "SELECT pg_tde_verify_key();");
$stdout =
  $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'relation is encrypted');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'relation can be read');

# Change provider and move file
move("$keydir/db1.keys", "$keydir/db2.keys");
$node->safe_psql('postgres',
	"SELECT pg_tde_change_database_key_provider_file('file-vault', '$keydir/db2.keys');"
);

$stdout = $node->safe_psql('postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");
is( $stdout,
	qq(1|file-vault|file|{"path" : "$keydir/db2.keys"}),
	'can list providers');

$node->safe_psql('postgres', "SELECT pg_tde_verify_key();");
$stdout =
  $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'relation is still encrypted');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'relation can still be read');

$node->restart;

$node->safe_psql('postgres', "SELECT pg_tde_verify_key();");
$stdout =
  $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'relation is encrypted after restart');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'relation can be read after restart');

# Move file, restart and then change provider
move("$keydir/db2.keys", "$keydir/db1.keys");

$node->restart;

$stderr = ($node->psql('postgres', "SELECT pg_tde_verify_key();"))[2];
like(
	$stderr,
	qr/ERROR:  key "test-key" not found in key provider "file-vault"/,
	'verificaiton fails after we have moved the key');
$stdout =
  $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'encryption check does not require a key');
$stderr = ($node->psql('postgres', 'SELECT * FROM test_enc ORDER BY id;'))[2];
like(
	$stderr,
	qr/ERROR:  key "test-key" not found in key provider "file-vault"/,
	'reading relation fails after we have moved the key');

# Restore the key provider
$node->safe_psql('postgres',
	"SELECT pg_tde_change_database_key_provider_file('file-vault', '$keydir/db1.keys');"
);

$stdout = $node->safe_psql('postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");
is( $stdout,
	qq(1|file-vault|file|{"path" : "$keydir/db1.keys"}),
	'can list providers');

$node->safe_psql('postgres', "SELECT pg_tde_verify_key();");
$stdout =
  $node->safe_psql('postgres', "SELECT pg_tde_is_encrypted('test_enc');");
is($stdout, 't', 'relation is encrypted after restoring provider');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'relation can be read after restoring provider');

$node->safe_psql('postgres', 'DROP EXTENSION pg_tde CASCADE;');

$node->stop;

done_testing();
