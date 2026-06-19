use strict;
use warnings FATAL => 'all';
use Fcntl 'SEEK_CUR';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $stderr;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('test-file-provider', '$keydir/db.keys');
	SELECT pg_tde_create_key_using_database_key_provider('key1', 'test-file-provider');
	SELECT pg_tde_create_key_using_database_key_provider('key2', 'test-file-provider');
));

corrupt_key_file("$keydir/db.keys");

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('key1', 'test-file-provider');"
);

like(
	$stderr,
	qr/WARNING:  invalid key: data length is zero/,
	'gets data length warning');
like(
	$stderr,
	qr/ERROR:  failed to retrieve principal key "key1" from key provider "test-file-provider"\nDETAIL:  Invalid key/,
	'gets error');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('key2', 'test-file-provider');"
);

like(
	$stderr,
	qr/WARNING:  invalid key: unsupported key length "4294967295"/,
	'gets data length warning');
like(
	$stderr,
	qr/ERROR:  failed to retrieve principal key "key2" from key provider "test-file-provider"\nDETAIL:  Invalid key/,
	'gets error');

$node->stop;

done_testing();

sub corrupt_key_file
{
	my ($keyfile) = @_;

	my $fh;
	open($fh, '+<', $keyfile)
	  or BAIL_OUT("open failed: $!");
	binmode $fh;

	# Corrupt the first page of the key file  by zeroing key data length.
	# Offset is TDE_KEY_NAME_LEN + MAX_KEY_DATA_SIZE. See keyring_api.h for details.
	sysseek($fh, 256 + 32, 0)
	  or BAIL_OUT("sysseek failed: $!");
	syswrite($fh, pack("L*", 0x00000000)) or BAIL_OUT("syswrite failed: $!");

	# Corrupt the second page of the key file by setting incorrect key length.
	# Offset is TDE_KEY_NAME_LEN + MAX_KEY_DATA_SIZE. See keyring_api.h for details.
	sysseek($fh, 256 + 32, SEEK_CUR)
	  or BAIL_OUT("sysseek failed: $!");
	syswrite($fh, pack("L*", 0xFFFFFFFF)) or BAIL_OUT("syswrite failed: $!");


	close($fh)
	  or BAIL_OUT("close failed: $!");
}
