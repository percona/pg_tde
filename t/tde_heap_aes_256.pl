#!/usr/bin/perl

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
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-vault');
));

# test_enc0 (simple create table w tde_heap and aes_128 and then add data when changed key size)
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc0 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc0 (k) VALUES ('multitude'), ('multitudinous');
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc0 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc0');

$node->append_conf('postgresql.conf', "pg_tde.cipher = 'aes_256'");
$node->restart;

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc0 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can still read test_enc0');

$node->safe_psql('postgres',
	"INSERT INTO test_enc0 (k) VALUES ('multitudinously'), ('multitudinousness');"
);

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc0 ORDER BY id;');
is( $stdout,
	"1|multitude\n2|multitudinous\n3|multitudinously\n4|multitudinousness",
	'can still read test_enc0');

# test_enc1 (simple create table w tde_heap)
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc1 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc1 (k) VALUES ('multitude'), ('multitudinous');
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc1 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc1');

# test_enc2 (create heap + alter to tde_heap)
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc2 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id));
	INSERT INTO test_enc2 (k) VALUES ('multitude'), ('multitudinous');
	ALTER TABLE test_enc2 SET ACCESS METHOD tde_heap;
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc2 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc2');

# test_enc3 (default_table_access_method)
$node->safe_psql(
	'postgres', qq(
	SET default_table_access_method = "tde_heap";
	CREATE TABLE test_enc3 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id));
	INSERT INTO test_enc3 (k) VALUES ('multitude'), ('multitudinous');
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc3 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc3');

# test_enc4 (create heap + alter default)
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc4 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING heap;
	INSERT INTO test_enc4 (k) VALUES ('multitude'), ('multitudinous');
	SET default_table_access_method = "tde_heap";
	ALTER TABLE test_enc4 SET ACCESS METHOD DEFAULT;
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc4 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc4');

# test_enc5 (create tde_heap + truncate)
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc5 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc5 (k) VALUES ('multitude'), ('multitudinous');
	CHECKPOINT;
	TRUNCATE test_enc5;
	INSERT INTO test_enc5 (k) VALUES ('multitude'), ('multitudinous');
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc5 ORDER BY id;');
is($stdout, "3|multitude\n4|multitudinous", 'can read test_enc5');

# test_enc6 (unencrypted table to cross check verify_table())
$node->safe_psql(
	'postgres', qq(
	CREATE TABLE test_enc6 (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING heap;
	INSERT INTO test_enc6 (k) VALUES ('multitude'), ('multitudinous');
));

$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc6 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc6');

$node->restart;

# Verify that we still can read all tables
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc1 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc1');
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc2 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc2');
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc3 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc3');
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc4 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc4');
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc5 ORDER BY id;');
is($stdout, "3|multitude\n4|multitudinous", 'can read test_enc5');
$stdout =
  $node->safe_psql('postgres', 'SELECT * FROM test_enc6 ORDER BY id;');
is($stdout, "1|multitude\n2|multitudinous", 'can read test_enc6');

# Verify if we can see the data in the files
unlike(slurp_relfile('test_enc1'),
	qr/multitud/, 'should not find plain text in test_enc1');
unlike(slurp_relfile('test_enc2'),
	qr/multitud/, 'should not find plain text in test_enc2');
unlike(slurp_relfile('test_enc3'),
	qr/multitud/, 'should not find plain text in test_enc3');
unlike(slurp_relfile('test_enc4'),
	qr/multitud/, 'should not find plain text in test_enc4');
unlike(slurp_relfile('test_enc5'),
	qr/multitud/, 'should not find plain text in test_enc5');
like(slurp_relfile('test_enc6'),
	qr/multitud/, 'should find plain text in test_enc6');

$node->safe_psql(
	'postgres', qq(
	DROP TABLE test_enc0;
	DROP TABLE test_enc1;
	DROP TABLE test_enc2;
	DROP TABLE test_enc3;
	DROP TABLE test_enc4;
	DROP TABLE test_enc5;
	DROP TABLE test_enc6;
	DROP EXTENSION pg_tde;
));

$node->stop;

done_testing();

sub slurp_relfile
{
	my ($table) = @_;

	my $file =
	  $node->safe_psql('postgres', "SELECT pg_relation_filepath('$table');");

	return slurp_file($node->data_dir . '/' . $file);
}
