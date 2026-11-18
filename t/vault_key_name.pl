use strict;
use warnings FATAL => 'all';
use IO::Socket::INET;
use POSIX qw(:sys_wait_h);
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

# Minimal fake Vault server logging the request lines it receives
my $tmpdir = PostgreSQL::Test::Utils::tempdir();
my $reqlog = "$tmpdir/requests";

my $srv = IO::Socket::INET->new(
	LocalAddr => '127.0.0.1',
	LocalPort => 0,
	Proto => 'tcp',
	Listen => 5,
	ReuseAddr => 1,) or BAIL_OUT("bind: $!");
my $port = $srv->sockport;

my $pid = fork() // BAIL_OUT("fork: $!");
if ($pid == 0)
{
	$SIG{TERM} = $SIG{INT} = 'DEFAULT';
	while (my $c = $srv->accept)
	{
		while (defined(my $line = <$c>))
		{
			$line =~ s/\r?\n$//;
			my $len = 0;
			while (defined(my $h = <$c>))
			{
				last if $h =~ /^\r?\n$/;
				$len = $1 if $h =~ /^Content-Length:\s*(\d+)/i;
			}
			read($c, my $body, $len) if $len;

			open(my $fh, '>>', $reqlog) or die;
			print $fh "$line\n";
			close $fh;

			my ($status, $resp) = ('404 Not Found', '{}');
			if ($line =~ m!^GET /v1/sys/mounts/!)
			{
				($status, $resp) = ('200 OK',
					'{"data":{"type":"kv","options":{"version":"2"}}}');
			}
			elsif ($line =~ m!^GET /v1/secret/metadata/!)
			{
				($status, $resp) = ('200 OK', '{}');
			}
			print $c "HTTP/1.1 $status\r\n"
			  . "Content-Type: application/json\r\n"
			  . "Content-Length: "
			  . length($resp) . "\r\n\r\n"
			  . $resp;
		}
		close $c;
	}
	POSIX::_exit(0);
}
close $srv;

END
{
	local $?;
	if ($pid)
	{
		kill 'TERM', $pid;
		waitpid($pid, 0);
	}
}

append_to_file("$tmpdir/token", 'dummy-token');

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');
$node->safe_psql('postgres',
	"SELECT pg_tde_add_database_key_provider_vault_v2('fake-vault', 'http://127.0.0.1:$port', 'secret', '$tmpdir/token', NULL);"
);

for my $name ('../../auth/token/revoke-self', '..', '.', '/a', 'a/', 'a//b',
	'a/./b', 'a/../b')
{
	my (undef, undef, $stderr) = $node->psql('postgres',
		"SELECT pg_tde_create_key_using_database_key_provider('$name', 'fake-vault');"
	);
	like(
		$stderr,
		qr/ERROR:  invalid key name "\Q$name\E" for key provider "fake-vault"/,
		"key name \"$name\" is rejected");
}

$node->safe_psql('postgres',
	"SELECT pg_tde_add_global_key_provider_vault_v2('fake-vault-global', 'http://127.0.0.1:$port', 'secret', '$tmpdir/token', NULL);"
);

my (undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_set_server_key_using_global_key_provider('../x', 'fake-vault-global');"
);
like(
	$stderr,
	qr/ERROR:  invalid key name "\.\.\/x" for key provider "fake-vault-global"/,
	'key name is rejected for server key');

unlike(slurp_file($reqlog), qr! /v1/secret/data/!,
	'no request for rejected key names');

for my $name ('a?b#c d%', 'a/b', '...', 'a..b')
{
	$node->psql('postgres',
		"SELECT pg_tde_create_key_using_database_key_provider('$name', 'fake-vault');"
	);
}

my $requests = slurp_file($reqlog);

like(
	$requests,
	qr!^GET /v1/secret/data/a%3Fb%23c%20d%25 HTTP!m,
	'special characters in key name are escaped');
like($requests, qr!^GET /v1/secret/data/a%2Fb HTTP!m,
	'slashes in key name are escaped');
like($requests, qr!^GET /v1/secret/data/\.\.\. HTTP!m,
	'dots that are not a dot segment are sent as is');
like($requests, qr!^GET /v1/secret/data/a\.\.b HTTP!m,
	'double dot inside a segment is sent as is');

$node->stop;

done_testing();
