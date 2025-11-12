#!/usr/bin/perl

# Test migration older format of pg_tde/*_keys files. It starts a cluster
# from preexising PGDATA. This PGDATA is the result of:
# - Created and run cluster with pg_tde 2.1.1 and encrypted WAL
# - Created encrypted table and insert data
# - Crashed server (kill -9)

use strict;
use warnings;
use File::Basename;
use Test::More;
use lib 't';
use pgtde;
use PostgreSQL::Test::Utils;

# Pre-created data dir was generated on PG18
my $pg_version = `pg_config --version`;
if ($pg_version !~ /PostgreSQL 18/)
{
	plan skip_all => 'PostgreSQL 18 required';
}

my $gzip = `which gzip`;
if (!defined $gzip || $gzip eq '')
{
	plan skip_all => 'gzip not available';
}

PGTDE::setup_files_dir(basename($0));

my $node = PostgreSQL::Test::Cluster->new('main');
my $port = $node->port;
my $host = $node->host;
my $data_dir = $node->data_dir;

mkdir $data_dir
  or die "Can't create folder $data_dir: $!\n";

system_or_bail('gzip', '-d', '-k', 't/keys_update_datadir.tar.gz');
system_or_bail(
	'tar',
	'xf' => 't/keys_update_datadir.tar',
	'-C' => $data_dir);

chmod(0700, "$data_dir")
  or die("unable to set permissions for $data_dir");

$node->append_conf('postgresql.conf', "unix_socket_directories = '$host'");
$node->append_conf('postgresql.conf', "listen_addresses = ''");
$node->append_conf('postgresql.conf', "port = '$port'");

$node->start;

# Compare the expected and out file. We don't check stderr as the possible
# difference of the collation version on the systems that test datadir was
# created, and the test was run on, will result in warnings
my ($result, $stdout, undef) = $node->psql(
	'postgres',
	'table test_enc',
	extra_params => [ '-q', '-A', '-t', '--no-psqlrc', '-U', 'vagrant' ]);

is($result, 0, "psql exit code");
is( $stdout, qq(1
2), 'data is correct after the keys migration');

$node->stop;

done_testing();
