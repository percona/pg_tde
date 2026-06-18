use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $stderr;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init(no_data_checksums => 1);
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;
$node->safe_psql(
	'postgres', "
CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('db', '$keydir/db.keys');
SELECT pg_tde_create_key_using_database_key_provider('server-key', 'db');
SELECT pg_tde_set_key_using_database_key_provider('server-key', 'db');

CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap;
INSERT INTO test_enc (k) VALUES (1), (2);
");

my $relfile =
  $node->safe_psql('postgres', "SELECT pg_relation_filepath('test_enc')");

$node->stop;

command_ok([ 'pg_tde_checksums', '--no-sync', '--enable', $node->data_dir ],
	'can enable checksums for encrypted tables');

$node->start;
is($node->safe_psql('postgres', 'SELECT * FROM test_enc'),
	"1\n2", 'can still read the table');
$node->stop;

$node->corrupt_page_checksum($relfile, 0);

$node->command_checks_all(
	[ 'pg_tde_checksums', '--check', $node->data_dir ],
	1,
	[qr/Bad checksums:.*1/],
	[qr/checksum verification failed/],
	'fails checksum validation after we corrupted a block');

$node->start;
(undef, undef, $stderr) = $node->psql('postgres', 'SELECT * FROM test_enc'),
  like(
	$stderr,
	qr/ERROR:  invalid page in block 0 of relation/,
	'cannot read the table after corrupting a block');
$node->stop;

done_testing();
