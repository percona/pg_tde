use strict;
use warnings;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $stdout;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
	SET allow_in_place_tablespaces = true;
	CREATE TABLESPACE test_tblspace LOCATION '';
	CREATE DATABASE tbc TABLESPACE = test_tblspace;
));

$node->safe_psql(
	'tbc', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-vault');

	CREATE TABLE country_table (
	     country_id   serial primary key,
	     country_name text unique not null,
	     continent    text not null
	) USING tde_heap;

	INSERT INTO country_table (country_name, continent)
	     VALUES ('Japan', 'Asia'),
	            ('UK', 'Europe'),
	            ('USA', 'North America');
));

$stdout = $node->safe_psql('tbc', 'SELECT * FROM country_table;');
is( $stdout,
	"1|Japan|Asia\n2|UK|Europe\n3|USA|North America",
	'can read table');

$node->safe_psql(
	'tbc', qq(
	SELECT pg_tde_create_key_using_database_key_provider('new-k', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('new-k', 'file-vault');
));

$node->restart;

$stdout = $node->safe_psql('tbc', 'SELECT * FROM country_table;');
is( $stdout,
	"1|Japan|Asia\n2|UK|Europe\n3|USA|North America",
	'can still read table');

$node->safe_psql('tbc', 'DROP EXTENSION pg_tde CASCADE;');

$node->safe_psql(
	'postgres', qq(
	DROP DATABASE tbc;
	DROP TABLESPACE test_tblspace;
));

$node->stop;

done_testing();
