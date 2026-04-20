use strict;
use warnings FATAL => 'all';

use Carp;
use JSON::XS;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;

my $orig_stdout;
my $orig_stderr;
my $bao_pid;

BEGIN
{
	# PostgreSQL's test suite redirects stdout/sterr to a log file so we need
	# to save them before the redirection happens.
	open($orig_stdout, '>&', \*STDOUT) or die $!;
	open($orig_stderr, '>&', \*STDERR) or die $!;
}

my @tests = qw(
  access_control
  alter_index
  change_access_method
  create_database
  default_principal_key
  delete_principal_key
  insert_update_delete
  key_provider
  kmip_test
  partition_table
  pg_tde_is_encrypted
  recreate_storage
  relocate
  tablespace
  toast_decrypt
  vault_v2_test
  version
);

my $node = PostgreSQL::Test::Cluster->new('regress');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

bao_setup();

IPC::Run::run [
	$ENV{PG_REGRESS},
	'--host' => $node->host,
	'--port' => $node->port,
	'--outputdir' => $ENV{'top_builddir'} || '.',
	@tests,
  ],
  '1>' => $orig_stdout,
  '2>' => $orig_stderr
  or exit $?;

$node->stop;

sub bao_setup
{
	my $bao_temp = PostgreSQL::Test::Utils::tempdir('bao');
	my $bao_port = PostgreSQL::Test::Cluster::get_free_port();

	$bao_pid = fork;
	unless ($bao_pid)
	{
		exec(
			'bao', 'server', '-dev', '-dev-tls',
			"-dev-listen-address=127.0.0.1:$bao_port",
			"-dev-cluster-json=$bao_temp/info");
	}

	wait_for_file("$bao_temp/info", '.');

	my $bao_info = decode_json(slurp_file("$bao_temp/info"));

	$ENV{'VAULT_ADDR'} = "https://127.0.0.1:$bao_port";
	$ENV{'VAULT_CACERT'} = $bao_info->{ca_cert_path};

	# We need to enable key/value version 1 engine for just for tests
	system_or_bail('bao', 'secrets', 'enable', '-path=kv-v1', '-version=1',
		'kv');

	# Create a test namespace for the tests to test namespace support
	system_or_bail('bao', 'namespace', 'create', 'pgns');
	system_or_bail('bao', 'secrets', 'enable', '-ns=pgns', '-path=secret',
		'-description="Production Secrets"', 'kv-v2');

	write_file("$bao_temp/token", $bao_info->{root_token});

	$ENV{'VAULT_ROOT_TOKEN_FILE'} = "$bao_temp/token";
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
	kill('TERM', $bao_pid) if $bao_pid;
}
