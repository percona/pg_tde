package PGTDE;

use PostgreSQL::Test::Utils;
use Time::HiRes qw(usleep);

# Copied from src/test/recovery/t/017_shm.pl
sub poll_start
{
	my ($node) = @_;

	my $max_attempts = 10 * $PostgreSQL::Test::Utils::timeout_default;
	my $attempts = 0;

	while ($attempts < $max_attempts)
	{
		$node->start(fail_ok => 1) && return 1;

		# Wait 0.1 second before retrying.
		usleep(100_000);

		# Clean up in case the start attempt just timed out or some such.
		$node->stop('fast', fail_ok => 1);

		$attempts++;
	}

	# Try one last time without fail_ok, which will BAIL_OUT unless it
	# succeeds.
	$node->start && return 1;
	return 0;
}

sub backup
{
	my ($node, $backup_name, %params) = @_;
	my $backup_dir = $node->backup_dir . '/' . $backup_name;
	my $name = $node->name;

	local %ENV = $node->_get_env();

	mkdir $backup_dir or die "mkdir($backup_dir) failed: $!";

	PostgreSQL::Test::RecursiveCopy::copypath($node->data_dir . '/pg_tde',
		$backup_dir . '/pg_tde');

	print "# Taking pg_basebackup $backup_name from node \"$name\"\n";
	PostgreSQL::Test::Utils::system_or_bail(
		'pg_tde_basebackup', '-D',
		$backup_dir, '-h',
		$node->host, '-p',
		$node->port, '--checkpoint',
		'fast', '--no-sync',
		'-E', @{ $params{backup_options} });
	print "# Backup finished\n";
	return;
}

1;
