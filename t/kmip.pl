use strict;
use warnings;
use CosmianKms;
use IO::Socket::INET;
use POSIX qw(:sys_wait_h);
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $cosmian_bin = CosmianKms::find_binary();
unless ($cosmian_bin)
{
	if ($ENV{PG_TEST_REQUIRE_COSMIAN_KMS})
	{
		BAIL_OUT("cosmian_kms required but not found "
			  . "(PG_TEST_REQUIRE_COSMIAN_KMS=1 set)");
	}
	plan skip_all =>
	  "cosmian_kms not on PATH; set COSMIAN_KMS_BIN to override";
}

# ---------------------------------------------------------------------------
# Cosmian + cert setup.
# ---------------------------------------------------------------------------
my $tmpdir = PostgreSQL::Test::Utils::tempdir();
CosmianKms::gen_certs($tmpdir);
my ($cosmian_h, $kmip_port, $http_port) =
  CosmianKms::start_with_free_port($cosmian_bin, $tmpdir);

END
{
	CosmianKms::stop($cosmian_h);
}

# ---------------------------------------------------------------------------
# PostgreSQL cluster.
# ---------------------------------------------------------------------------
my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');

# Provider + key + encrypted table.
$node->safe_psql('postgres', <<SQL);
SELECT pg_tde_add_database_key_provider_kmip(
    'kmip-prov', '127.0.0.1', $kmip_port,
    '$tmpdir/client.pem', '$tmpdir/client.key', '$tmpdir/ca.pem');
SELECT pg_tde_create_key_using_database_key_provider(
    'kmip-key', 'kmip-prov');
SELECT pg_tde_set_key_using_database_key_provider(
    'kmip-key', 'kmip-prov');
CREATE TABLE test_enc(
    id SERIAL, k INTEGER NOT NULL, PRIMARY KEY(id)) USING tde_heap;
INSERT INTO test_enc(k) VALUES (1), (2), (3);
SQL

is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3", 'encrypted insert round-trip');

# Restart → cold cache → KMIP re-fetch.
$node->restart;
is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3", 'decrypts after restart (KMIP re-fetch)');

# Key rotation + post-rotation insert.
$node->safe_psql('postgres', <<SQL);
SELECT pg_tde_create_key_using_database_key_provider(
    'kmip-key2', 'kmip-prov');
SELECT pg_tde_set_key_using_database_key_provider(
    'kmip-key2', 'kmip-prov');
INSERT INTO test_enc(k) VALUES (4), (5);
SQL

is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3\n4\n5", 'rows readable across key rotation');

# Restart after rotation.
$node->restart;
is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3\n4\n5", 'rows readable after restart following rotation');

# ---------------------------------------------------------------------------
# Negative path: swap in a fresh KMIP server (same TLS/port, empty DB) and
# confirm encrypted reads fail because the principal key cannot be located.
# ---------------------------------------------------------------------------
{
	$node->stop;

	CosmianKms::stop($cosmian_h);
	$cosmian_h =
	  CosmianKms::start_on_ports($cosmian_bin, $tmpdir, $kmip_port,
		$http_port);

	$node->start;

	my (undef, undef, $stderr) =
	  $node->psql('postgres', 'SELECT k FROM test_enc ORDER BY id;');
	like(
		$stderr,
		qr/not found in key provider/i,
		'encrypted read fails when KMIP server has no matching key');
}

# ---------------------------------------------------------------------------
# Negative path: pg_tde fails fast (<= 5s) when KMIP endpoint accepts TCP
# but immediately closes (no TLS, no KMIP).
# ---------------------------------------------------------------------------
sub _bind_and_fork_reject_listener
{
	my $srv = IO::Socket::INET->new(
		LocalAddr => '127.0.0.1',
		LocalPort => 0,
		Proto => 'tcp',
		Listen => 5,
		ReuseAddr => 1,) or BAIL_OUT("negative-path bind: $!");
	my $port = $srv->sockport;

	my $pid = fork() // BAIL_OUT("negative-path fork: $!");
	if ($pid == 0)
	{
		# Reset the SIGTERM/SIGINT handlers PostgreSQL::Test::Cluster
		# installs (which `die` on signal). Otherwise the child's TERM
		# would unwind through Perl's END blocks — including the
		# cluster's END that runs `pg_ctl stop -m immediate`, killing
		# the postgres server we are mid-test against.
		$SIG{TERM} = $SIG{INT} = 'DEFAULT';
		# Child: accept-then-close on the inherited socket until killed.
		while (my $c = $srv->accept) { close $c }
		POSIX::_exit(0);
	}
	# Parent: close our copy so only the child holds the socket.
	close $srv;
	return ($pid, $port);
}

{
	my ($pid, $nope_port) = _bind_and_fork_reject_listener();

	my (undef, undef, $stderr) = $node->psql('postgres', <<SQL);
SELECT pg_tde_add_database_key_provider_kmip(
    'will-not-work', '127.0.0.1', $nope_port,
    '$tmpdir/client.pem', '$tmpdir/client.key', '$tmpdir/ca.pem');
SQL

	kill 'TERM', $pid;
	waitpid($pid, 0);

	like(
		$stderr,
		qr/SSL error|BIO_do_connect|handshake|EOF/i,
		"negative path produced expected failure");
}

$node->stop;

done_testing();
