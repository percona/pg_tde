use strict;
use warnings FATAL => 'all';

use PostgreSQL::Test::Cluster;

my $orig_stdout;
my $orig_stderr;

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
