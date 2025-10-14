#!/usr/bin/perl

use strict;
use warnings;
use File::Basename;
use File::Copy;
use Test::More;
use lib 't';
use pgtde;

PGTDE::setup_files_dir(basename($0));

unlink('/tmp/change_key_provider_1.per');
unlink('/tmp/change_key_provider_2.per');

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
if ($node->pg_version >= 18)
{
	$node->append_conf('postgresql.conf', 'io_method = sync');
}
$node->start;

PGTDE::psql($node, 'postgres', 'CREATE EXTENSION pg_tde;');

PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_add_database_key_provider_file('file-vault', '/tmp/change_key_provider_1.per');"
);
PGTDE::psql($node, 'postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_create_key_using_database_key_provider('test-key', 'file-vault');"
);
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('test-key', 'file-vault');"
);

PGTDE::psql($node, 'postgres',
	'CREATE TABLE test_enc (id serial, k integer, PRIMARY KEY (id)) USING tde_heap;'
);
PGTDE::psql($node, 'postgres', 'INSERT INTO test_enc (k) VALUES (5), (6);');

PGTDE::psql($node, 'postgres', "SELECT pg_tde_verify_key();");
PGTDE::psql($node, 'postgres', "SELECT pg_tde_is_encrypted('test_enc');");
PGTDE::psql($node, 'postgres', 'SELECT * FROM test_enc ORDER BY id;');

# Change provider and move file
PGTDE::append_to_result_file(
	"-- mv /tmp/change_key_provider_1.per /tmp/change_key_provider_2.per");
move('/tmp/change_key_provider_1.per', '/tmp/change_key_provider_2.per');
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_change_database_key_provider_file('file-vault', '/tmp/change_key_provider_2.per');"
);
PGTDE::psql($node, 'postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");

PGTDE::psql($node, 'postgres', "SELECT pg_tde_verify_key();");
PGTDE::psql($node, 'postgres', "SELECT pg_tde_is_encrypted('test_enc');");
PGTDE::psql($node, 'postgres', 'SELECT * FROM test_enc ORDER BY id;');

PGTDE::append_to_result_file("-- server restart");
$node->restart;

PGTDE::psql($node, 'postgres', "SELECT pg_tde_verify_key();");
PGTDE::psql($node, 'postgres', "SELECT pg_tde_is_encrypted('test_enc');");
PGTDE::psql($node, 'postgres', 'SELECT * FROM test_enc ORDER BY id;');

# Move file, restart and then change provider
PGTDE::append_to_result_file(
	"-- mv /tmp/change_key_provider_2.per /tmp/change_key_provider_1.per");
move('/tmp/change_key_provider_2.per', '/tmp/change_key_provider_1.per');

PGTDE::append_to_result_file("-- server restart");
$node->restart;

PGTDE::psql($node, 'postgres', "SELECT pg_tde_verify_key();");
PGTDE::psql($node, 'postgres', "SELECT pg_tde_is_encrypted('test_enc');");
PGTDE::psql($node, 'postgres', 'SELECT * FROM test_enc ORDER BY id;');

PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_change_database_key_provider_file('file-vault', '/tmp/change_key_provider_1.per');"
);
PGTDE::psql($node, 'postgres',
	"SELECT * FROM pg_tde_list_all_database_key_providers();");

PGTDE::psql($node, 'postgres', "SELECT pg_tde_verify_key();");
PGTDE::psql($node, 'postgres', "SELECT pg_tde_is_encrypted('test_enc');");
PGTDE::psql($node, 'postgres', 'SELECT * FROM test_enc ORDER BY id;');

PGTDE::psql($node, 'postgres', 'DROP EXTENSION pg_tde CASCADE;');

$node->stop;

# Compare the expected and out file
my $compare = PGTDE->compare_results();

is($compare, 0,
	"Compare Files: $PGTDE::expected_filename_with_path and $PGTDE::out_filename_with_path files."
);

done_testing();
