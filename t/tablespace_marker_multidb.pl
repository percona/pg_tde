#!/usr/bin/perl

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

unlink('/tmp/pg_tde_multidb_a.per');
unlink('/tmp/pg_tde_multidb_b.per');

my $node = PostgreSQL::Test::Cluster->new('multidb');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->append_conf('postgresql.conf', 'allow_in_place_tablespaces = true');
$node->start;

$node->safe_psql(
	'postgres', q{
    CREATE EXTENSION pg_tde;
    CREATE TABLESPACE multi_ts LOCATION '';
    CREATE DATABASE db_a;
    CREATE DATABASE db_b;
});

$node->safe_psql(
	'db_a', q{
    CREATE EXTENSION pg_tde;
    SELECT pg_tde_add_database_key_provider_file('fv', '/tmp/pg_tde_multidb_a.per');
    SELECT pg_tde_create_key_using_database_key_provider('k','fv');
    SELECT pg_tde_set_key_using_database_key_provider('k','fv');
    CREATE TABLE t_a(x int) TABLESPACE multi_ts;
});

$node->safe_psql(
	'db_b', q{
    CREATE EXTENSION pg_tde;
    SELECT pg_tde_add_database_key_provider_file('fv', '/tmp/pg_tde_multidb_b.per');
    SELECT pg_tde_create_key_using_database_key_provider('k','fv');
    SELECT pg_tde_set_key_using_database_key_provider('k','fv');
    CREATE TABLE t_b(x int) TABLESPACE multi_ts;
});

# With a table in each DB, marking must fail.
my ($ret, $out, $err) = $node->psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('multi_ts');");
isnt($ret, 0, 'mark fails with relations in multiple DBs');
like($err, qr/not empty/, 'got expected error');

# Drop from db_a only — still not empty.
$node->safe_psql('db_a', 'DROP TABLE t_a;');
($ret, $out, $err) = $node->psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('multi_ts');");
isnt($ret, 0, 'mark still fails with relation remaining in db_b');

# Drop from db_b too — now empty.
$node->safe_psql('db_b', 'DROP TABLE t_b;');
$node->safe_psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('multi_ts');");
pass('mark succeeds after clearing both DBs');

$node->stop;
done_testing();
