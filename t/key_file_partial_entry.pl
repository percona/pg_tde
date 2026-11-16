use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-provider', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('key1', 'file-provider');
	SELECT pg_tde_set_key_using_database_key_provider('key1', 'file-provider');
	CREATE TABLE plain (x int);
));

my $db_oid = $node->safe_psql('postgres',
	"SELECT oid FROM pg_database WHERE datname = 'postgres'");
my $map_file = $node->data_dir . "/pg_tde/${db_oid}_keys";
my $header_size = -s $map_file;

# Simulate a failed write of a key map entry
append_to_file($map_file, 'x');

is($node->safe_psql('postgres', 'SELECT count(*) FROM plain'),
	'0', 'key lookup works with an incomplete last entry');

$node->safe_psql(
	'postgres', q(
	CREATE TABLE enc (x int) USING tde_heap;
	INSERT INTO enc VALUES (42);
));
my $entry_size = (-s $map_file) - $header_size;
cmp_ok($entry_size, '>', 1, 'incomplete entry is overwritten by the next key');

$node->safe_psql('postgres', 'CREATE TABLE enc2 (x int) USING tde_heap');
is( -s $map_file,
	$header_size + 2 * $entry_size,
	'key map file is aligned again');

$node->restart;
is($node->safe_psql('postgres', 'SELECT x FROM enc'),
	'42', 'encrypted table is readable');

$node->safe_psql('postgres', 'DROP TABLE enc; DROP TABLE enc2;');

# An incomplete entry is never a key, it does not block deleting the principal
# key
append_to_file($map_file, 'x');

my ($ret, undef, $stderr) =
  $node->psql('postgres', 'SELECT pg_tde_delete_key()');
is($ret, 0, 'principal key can be deleted with an incomplete last entry');
like(
	$stderr,
	qr/WARNING:  key file "[^"]+" has an incomplete entry at offset \d+/,
	'incomplete entry is reported when counting keys');
ok(!-e $map_file, 'key map file is removed');

$node->stop;

done_testing();
