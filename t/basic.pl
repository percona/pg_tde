use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my ($stdout, $stderr);

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');

$stdout = $node->safe_psql(
	'postgres',
	q{
		SELECT
			pg_proc.oid::regprocedure
		FROM
			pg_catalog.pg_proc
			JOIN pg_catalog.pg_language ON prolang = pg_language.oid
			LEFT JOIN LATERAL aclexplode(proacl) ON TRUE
		WHERE
			proname LIKE 'pg_tde%' AND
			(lanname = 'c' OR prosecdef) AND
			(grantee IS NULL OR grantee = 0)
		ORDER BY pg_proc.oid::regprocedure::text;
	});
is( $stdout,
	"pg_tde_is_encrypted(regclass)\npg_tde_version()",
	'only whitelisted functions are callable by public');

$stdout = $node->safe_psql('postgres',
	"SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_tde';");
is($stdout, 'pg_tde|2.2', 'is installed with right version');

(undef, undef, $stderr) = $node->psql('postgres',
	'CREATE TABLE test_enc (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap;'
);
like(
	$stderr,
	qr/ERROR:  principal key not configured/,
	'complains about key not being set');

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-vault');

	CREATE TABLE test_enc (id SERIAL, k VARCHAR(32), PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc (k) VALUES ('foobar'), ('barfoo');
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|foobar\n2|barfoo", 'can read encrypted table');

$node->restart;

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|foobar\n2|barfoo", 'can read encrypted table after restart');

# Verify that we can't see the data in the file
unlike(slurp_relfile('test_enc'), qr/foo/, 'should not find plain text');

# An encrypted table can be dropped even if we don't have access to the principal key.
$node->stop;
unlink("$keydir/db.keys");
$node->start;
(undef, undef, $stderr) =
  $node->psql('postgres', 'SELECT pg_tde_verify_key()');
like(
	$stderr,
	qr/ERROR:  key "test-db-key" not found in key provider "file-vault"/,
	'complains about missing key');
$node->safe_psql('postgres', 'DROP TABLE test_enc;');

$node->safe_psql('postgres', 'DROP EXTENSION pg_tde;');

$node->stop;

done_testing();

sub slurp_relfile
{
	my ($table) = @_;

	my $file =
	  $node->safe_psql('postgres', "SELECT pg_relation_filepath('$table');");

	return slurp_file($node->data_dir . '/' . $file);
}
