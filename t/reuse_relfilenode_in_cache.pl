#!/usr/bin/perl

use strict;
use warnings;
use File::Basename;
use Test::More;
use lib 't';
use pgtde;

PGTDE::setup_files_dir(basename($0));

unlink('/tmp/reuse_relfilenode_in_cache.per');

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf(
	'postgresql.conf', q[
	full_page_writes = off
	shared_buffers = 1MB
	shared_preload_libraries = 'pg_tde'
]);
$node->start;

PGTDE::psql($node, 'postgres', 'CREATE EXTENSION pg_tde;');
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_add_global_key_provider_file('global-keyring', '/tmp/reuse_relfilenode_in_cache.per');"
);
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('default-key', 'global-keyring');"
);
PGTDE::psql($node, 'postgres',
	"SELECT pg_tde_set_default_key_using_global_key_provider('default-key', 'global-keyring');"
);

# Create a template with a table in it to ensure the relfilenodes get reused,
# and fill the table with more data than can fit in shared buffers. We give the
# template a fixed OID just to ensure there won't be a conflict with the OID of
# the test database we create later.
PGTDE::psql($node, 'postgres',
	"CREATE DATABASE conflict_db_template OID = 50000;");
PGTDE::psql($node, 'conflict_db_template', 'CREATE EXTENSION pg_tde;');
PGTDE::psql($node, 'conflict_db_template',
	"CREATE TABLE large(id serial primary key, dataa text, datab text) USING tde_heap;"
);
PGTDE::psql($node, 'conflict_db_template',
	"INSERT INTO large(dataa, datab) SELECT g.i::text, 1 FROM generate_series(1, 4000) g(i);"
);

# Use a fixed OID for the test database so we can ensure it reuses the same
# relfilenodes.
PGTDE::psql($node, 'postgres',
	"CREATE DATABASE conflict_db TEMPLATE conflict_db_template OID = 50001;");

# Large table in postgres to fill shared_buffers and force eviction.
PGTDE::psql($node, 'postgres', 'CREATE EXTENSION pg_prewarm;');
PGTDE::psql($node, 'postgres', 'CREATE TABLE replace_sb(data text);');
PGTDE::psql($node, 'postgres',
	"INSERT INTO replace_sb(data) SELECT random()::text FROM generate_series(1, 15000);"
);

# Long-running session: holds SMgrRelation structs open across txn boundary.
my $psql_timeout = IPC::Run::timer($PostgreSQL::Test::Utils::timeout_default);
my %bg = (stdin => '', stdout => '', stderr => '');
$bg{run} = IPC::Run::start(
	[
		'psql', '--no-psqlrc', '--no-align',
		'--file' => '-',
		'--dbname' => $node->connstr('postgres')
	],
	'<' => \$bg{stdin},
	'>' => \$bg{stdout},
	'2>' => \$bg{stderr},
	$psql_timeout);

send_query_and_wait(\%bg, q[BEGIN;], qr/BEGIN/m);

# Dirty shared buffers, then evict through the long-running session.
PGTDE::psql($node, 'conflict_db', "UPDATE large SET datab = 1;");
cause_eviction(\%bg);

# Recreate database with same OID and same relfilenodes. The reuse of cached
# relfilenodes can happen without a DROP/CREATE database, but it's the easiest
# way to reproduce.
PGTDE::psql($node, 'postgres', "DROP DATABASE conflict_db;");
PGTDE::psql($node, 'postgres',
	"CREATE DATABASE conflict_db TEMPLATE conflict_db_template OID = 50001;");

# Dirty buffers again and evict.
PGTDE::psql($node, 'conflict_db', "UPDATE large SET datab = 2;");
cause_eviction(\%bg);

# Verify data is readable.
PGTDE::psql($node, 'conflict_db',
	"SELECT datab, count(*) FROM large GROUP BY 1 ORDER BY 1 LIMIT 10;");

$bg{stdin} .= "\\q\n";
$bg{run}->finish;
$node->stop;

# Compare the expected and out file
my $compare = PGTDE->compare_results();

is($compare, 0,
	"Compare Files: $PGTDE::expected_filename_with_path and $PGTDE::out_filename_with_path files."
);

done_testing();

# These two functions are copied from postgresql's test/recovery/t/032_relfilenode_reuse.pl

sub cause_eviction
{
	my ($psql) = @_;
	send_query_and_wait(
		$psql,
		q[SELECT SUM(pg_prewarm(oid)) warmed_buffers FROM pg_class WHERE pg_relation_filenode(oid) != 0;],
		qr/warmed_buffers/m);
}

sub send_query_and_wait
{
	my ($psql, $query, $untl) = @_;

	$psql_timeout->reset();
	$psql_timeout->start();

	$$psql{stdin} .= $query;
	$$psql{stdin} .= "\n";

	$$psql{run}->pump_nb();
	while (1)
	{
		last if $$psql{stdout} =~ /$untl/;

		if ($psql_timeout->is_expired)
		{
			BAIL_OUT("aborting wait: program timed out\n"
				  . "stream contents: >>$$psql{stdout}<<\n"
				  . "pattern searched for: $untl\n");
			return 0;
		}
		if (not $$psql{run}->pumpable())
		{
			BAIL_OUT("aborting wait: program died\n"
				  . "stream contents: >>$$psql{stdout}<<\n"
				  . "pattern searched for: $untl\n");
			return 0;
		}
		$$psql{run}->pump();
	}

	$$psql{stdout} = '';
	return 1;
}
