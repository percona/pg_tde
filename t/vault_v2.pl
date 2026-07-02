use strict;
use warnings FATAL => 'all';
use Carp;
use File::Spec;
use IPC::Run;
use JSON::XS;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $bao_bin = find_binary();
unless ($bao_bin)
{
	if ($ENV{PG_TEST_REQUIRE_OPENBAO})
	{
		BAIL_OUT("bao required but not found "
			  . "(PG_TEST_REQUIRE_OPENBAO=1 set)");
	}
	plan skip_all => "bao not on PATH; set OPENBAO_BIN to override";
}

my $baoh;

my ($ret, $stdout, $stderr);

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

my $bao = bao_setup($bao_bin);

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');

($ret, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_add_database_key_provider_vault_v2('vault-incorrect', 'https://127.0.0.1:@{[$bao->{port}]}', 'DUMMY-MOUNT-PATH', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');"
);
is($ret, 0, 'adds key provider despite path not existing');
like(
	$stderr,
	qr!WARNING:  failed to get mount info for "https://127\.0\.0\.1:\d+" at mountpoint "DUMMY-MOUNT-PATH" \(HTTP 400\)!,
	'warns if mount path does not exist');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_add_database_key_provider_vault_v2('vault-incorrect', 'https://127.0.0.1:@{[$bao->{port}]}', 'cubbyhole', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');"
);
like(
	$stderr,
	qr/ERROR:  vault mount at "cubbyhole" has unsupported engine type "cubbyhole"/,
	"fails as it's not supported engine type");

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_add_database_key_provider_vault_v2('vault-incorrect', 'https://127.0.0.1:@{[$bao->{port}]}', 'kv-v1', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');"
);
like(
	$stderr,
	qr!ERROR:  vault mount at "kv-v1" has unsupported Key/Value engine version "1"!,
	"fails as it's not supported engine version");

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_add_database_key_provider_vault_v2('vault-v2', 'https://127.0.0.1:@{[$bao->{port}]}', 'secret', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');
	SELECT pg_tde_create_key_using_database_key_provider('vault-v2-key', 'vault-v2');
	SELECT pg_tde_set_key_using_database_key_provider('vault-v2-key', 'vault-v2');

	CREATE TABLE test_enc (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc (x) VALUES (1), (2);
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc;');
is($stdout, "1\n2", 'can read test_enc');

$stdout = $node->safe_psql('postgres', 'SELECT pg_tde_verify_key();');
is($stdout, '', 'key verification succeeds');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_add_database_key_provider_vault_v2('will-not-work', 'https://127.0.0.1:61', 'secret', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');"
);
like(
	$stderr,
	qr/ERROR:  HTTP\(S\) request to keyring provider "will-not-work" failed/,
	"creating provider fails if we can't connect to vault");

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_change_database_key_provider_vault_v2('vault-v2', 'https://127.0.0.1:61', 'secret', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}');"
);
like(
	$stderr,
	qr/ERROR:  HTTP\(S\) request to keyring provider "vault-v2" failed/,
	"changing provider fails if we can't connect to vault");

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_change_database_key_provider_vault_v2('vault-v2', 'https://127.0.0.1:@{[$bao->{port}]}', 'secret', '@{[$bao->{root_token_path}]}', NULL);"
);
like(
	$stderr,
	qr/ERROR:  HTTP\(S\) request to keyring provider "vault-v2" failed/,
	'HTTPS without cert fails');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_change_database_key_provider_vault_v2('vault-v2', 'http://127.0.0.1:@{[$bao->{port}]}', 'secret', '@{[$bao->{root_token_path}]}', NULL);"
);
like(
	$stderr,
	qr!WARNING:  failed to get mount info for "http://127\.0\.0\.1:\d+" at mountpoint "secret" \(HTTP 400\)!,
	'HTTP against HTTPS server warns');
like(
	$stderr,
	qr!ERROR:  Listing secrets of "http://127\.0\.0\.1:\d+" at mountpoint "secret" failed!,
	'HTTP against HTTPS server fails');

# Test namespaces

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_add_database_key_provider_vault_v2('vault-v2ns', 'https://127.0.0.1:@{[$bao->{port}]}', 'secret', '@{[$bao->{root_token_path}]}', '@{[$bao->{ca_cert_path}]}', 'pgns');
	SELECT pg_tde_create_key_using_database_key_provider('vault-v2-key-in-ns', 'vault-v2ns');
	SELECT pg_tde_set_key_using_database_key_provider('vault-v2-key-in-ns', 'vault-v2ns');

	CREATE TABLE test_enc_ns (x int PRIMARY KEY) USING tde_heap;
	INSERT INTO test_enc_ns (x) VALUES (1), (2);
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc_ns;');
is($stdout, "1\n2", 'can read test_enc_ns');

$stdout = $node->safe_psql('postgres', 'SELECT pg_tde_verify_key();');
is($stdout, '', 'key verification succeeds with namespaces');

$node->stop;

done_testing();

sub bao_setup
{
	my ($bao_bin) = @_;
	my $temp = PostgreSQL::Test::Utils::tempdir('openbao');
	my $port = PostgreSQL::Test::Cluster::get_free_port;

	$baoh = IPC::Run::start(
		[
			$bao_bin, 'server', '-dev', '-dev-tls',
			"-dev-listen-address=127.0.0.1:$port",
			"-dev-cluster-json=$temp/info"
		]);

	wait_for_file("$temp/info", '.');

	my $cluster_info = decode_json(slurp_file("$temp/info"));

	local %ENV = %ENV;
	$ENV{'VAULT_ADDR'} = "https://127.0.0.1:$port";
	$ENV{'VAULT_CACERT'} = $cluster_info->{ca_cert_path};

	# Enable key/value version 1 engine
	system_or_bail($bao_bin, 'secrets', 'enable', '-path=kv-v1', '-version=1',
		'kv');

	# Create a test namespace for the tests to test namespace support
	system_or_bail($bao_bin, 'namespace', 'create', 'pgns');
	system_or_bail($bao_bin, 'secrets', 'enable', '-ns=pgns', '-path=secret',
		'-description="Production Secrets"', 'kv-v2');

	write_file("$temp/token", $cluster_info->{root_token});

	return {
		port => $port,
		root_token_path => "$temp/token",
		ca_cert_path => $cluster_info->{ca_cert_path},
	};
}

sub find_binary
{
	if (my $override = $ENV{OPENBAO_BIN})
	{
		return $override if -x $override;
		diag("OPENBAO_BIN=$override is not executable; ignoring");
	}

	for my $dir (File::Spec->path)
	{
		my $candidate = File::Spec->catfile($dir, 'bao');
		return $candidate if -x $candidate;
	}
	return undef;
}

sub write_file
{
	my ($filename, $str) = @_;
	open my $fh, ">", $filename
	  or croak "could not write \"$filename\": $!";
	print $fh $str;
	close $fh;
	return;
}

# Taken from PostgreSQL 19
sub wait_for_file
{
	my ($filename, $regexp, $offset) = @_;
	$offset = 0 unless defined $offset;

	my $max_attempts = 10 * $PostgreSQL::Test::Utils::timeout_default;
	my $attempts = 0;

	while ($attempts < $max_attempts)
	{
		if (-e $filename)
		{
			my $contents = slurp_file($filename, $offset);
			return $offset + length($contents) if ($contents =~ m/$regexp/);
		}

		# Wait 0.1 second before retrying.
		Time::HiRes::usleep(100_000);

		$attempts++;
	}

	croak "timed out waiting for file $filename contents to match: $regexp";
}

END
{
	$baoh->kill_kill if $baoh;
}
