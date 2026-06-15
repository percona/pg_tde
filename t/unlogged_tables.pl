#!/usr/bin/perl

use strict;
use warnings;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;
use pgtde;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
    CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-key', 'file-vault');

	CREATE UNLOGGED TABLE t (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO t SELECT generate_series(1, 4);

	CHECKPOINT;
));

$node->kill9;

PGTDE::poll_start($node);

my $stdout = $node->safe_psql('postgres', 'TABLE t;');
is($stdout, "", "table is empty");

$node->safe_psql('postgres', 'INSERT INTO t SELECT generate_series(1, 4);');

$node->stop;

done_testing();
