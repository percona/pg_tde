package CosmianKms;

use strict;
use warnings;
use File::Path qw(make_path);
use File::Spec;
use IPC::Run qw(start);
use PostgreSQL::Test::Utils;
use Time::HiRes qw(usleep time);
use POSIX       qw(:sys_wait_h);
use Test::More;

sub find_binary
{
	if (my $override = $ENV{COSMIAN_KMS_BIN})
	{
		return $override if -x $override;
		diag("COSMIAN_KMS_BIN=$override is not executable; ignoring");
	}

	for my $dir (File::Spec->path)
	{
		my $candidate = File::Spec->catfile($dir, 'cosmian_kms');
		return $candidate if -x $candidate;
	}
	return undef;
}

sub gen_certs
{
	my ($dir) = @_;
	make_path($dir);

	# CA
	system_or_bail(
		'openssl', 'req', '-x509', '-newkey',
		'rsa:2048', '-nodes', '-days', '1',
		'-keyout', "$dir/ca.key", '-out', "$dir/ca.pem",
		'-subj', '/CN=pg_tde-test-ca');

	# Server CSR + signed cert
	system_or_bail(
		'openssl', 'req',
		'-newkey', 'rsa:2048',
		'-nodes', '-keyout',
		"$dir/server.key", '-out',
		"$dir/server.csr", '-subj',
		'/CN=127.0.0.1', '-addext',
		'subjectAltName=IP:127.0.0.1');
	system_or_bail(
		'openssl', 'x509',
		'-req', '-in',
		"$dir/server.csr", '-CA',
		"$dir/ca.pem", '-CAkey',
		"$dir/ca.key", '-CAcreateserial',
		'-days', '1',
		'-out', "$dir/server.pem",
		'-copy_extensions', 'copy');

	# Server PKCS#12 bundle
	system_or_bail(
		'openssl', 'pkcs12', '-export', '-out',
		"$dir/server.p12", '-inkey', "$dir/server.key", '-in',
		"$dir/server.pem", '-password', 'pass:test');

	# Client CSR + signed cert
	system_or_bail(
		'openssl', 'req', '-newkey', 'rsa:2048',
		'-nodes', '-keyout', "$dir/client.key", '-out',
		"$dir/client.csr", '-subj', '/CN=pg_tde-client');
	system_or_bail(
		'openssl', 'x509',
		'-req', '-in',
		"$dir/client.csr", '-CA',
		"$dir/ca.pem", '-CAkey',
		"$dir/ca.key", '-CAcreateserial',
		'-days', '1',
		'-out', "$dir/client.pem");
}

sub _wait_ready
{
	my ($http_port) = @_;
	my $deadline = time() + 15;
	while (time() < $deadline)
	{
		my $rc =
		  system("curl -fsSk -m 1 https://127.0.0.1:$http_port/version "
			  . "> /dev/null 2>&1");
		return 1 if ($rc >> 8) == 0;
		usleep(200_000);
	}
	return 0;
}

sub _write_toml
{
	my ($dir, $kmip_port, $http_port) = @_;
	my $toml = <<"TOML";
default_username = "admin"

[db]
database_type = "sqlite"
sqlite_path   = "$dir/db"
clear_database = true

[tls]
tls_p12_file         = "$dir/server.p12"
tls_p12_password     = "test"
clients_ca_cert_file = "$dir/ca.pem"

[socket_server]
socket_server_start    = true
socket_server_port     = $kmip_port
socket_server_hostname = "127.0.0.1"

[http]
port     = $http_port
hostname = "127.0.0.1"

[logging]
rust_log = "info,cosmian_kms=info"
TOML
	open(my $fh, '>', "$dir/kms.toml")
	  or BAIL_OUT("write kms.toml: $!");
	print $fh $toml;
	close $fh;
}

sub _spawn
{
	my ($bin, $dir, $stderr_ref) = @_;

	# Note: Cosmian silently ignores CLI flags when any TOML config
	# is present, specify everything in the config file
	my @cmd = ($bin, '-c', "$dir/kms.toml");

	# Cosmian needs OPENSSL_MODULES properly set, try to autodetect
	# it based on common locations if currently unset
	local %ENV = %ENV;
	if (!$ENV{OPENSSL_MODULES})
	{
		for my $d (
			'/usr/local/cosmian/lib/ossl-modules',
			'/usr/lib64/ossl-modules',
			'/usr/lib/x86_64-linux-gnu/ossl-modules',
			'/usr/lib/aarch64-linux-gnu/ossl-modules')
		{
			if (-d $d) { $ENV{OPENSSL_MODULES} = $d; last; }
		}
	}

	return start(\@cmd, '>', '/dev/null', '2>', $stderr_ref);
}

sub start_on_ports
{
	my ($bin, $dir, $kmip_port, $http_port) = @_;

	_write_toml($dir, $kmip_port, $http_port);

	my $stderr = '';
	my $h = _spawn($bin, $dir, \$stderr);
	BAIL_OUT("cosmian_kms spawn failed") unless $h;

	if (!_wait_ready($http_port))
	{
		$h->kill_kill;
		BAIL_OUT("cosmian_kms (kmip=$kmip_port http=$http_port) "
			  . "readiness timed out\nstderr:\n$stderr");
	}
	return $h;
}

sub start_with_free_port
{
	my ($bin, $dir) = @_;
	my $kmip_port = PostgreSQL::Test::Cluster::get_free_port();
	my $http_port = PostgreSQL::Test::Cluster::get_free_port();

	my $h = start_on_ports($bin, $dir, $kmip_port, $http_port);
	return ($h, $kmip_port, $http_port);
}

sub stop
{
	my ($h) = @_;
	return unless $h;
	$h->kill_kill;
}

1;
