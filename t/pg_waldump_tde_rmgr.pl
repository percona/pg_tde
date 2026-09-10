# Tests that pg_tde_waldump recognises the pg_tde custom resource manager:
# it must print "rmgr: pg_tde" with a proper description instead of the
# generic "rmgr: custom140 ... desc: UNKNOWN (%d) rmid: %d", and it must
# accept "--rmgr=pg_tde" (as well as the legacy "--rmgr=custom140") to
# filter WAL records.

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf(
	'postgresql.conf', q{
autovacuum = off
checkpoint_timeout = 1h
shared_preload_libraries = 'pg_tde'
});
$node->start;

my $start_lsn =
  $node->safe_psql('postgres', q{SELECT pg_current_wal_insert_lsn()});

# Generate pg_tde rmgr WAL records: XLOG_TDE_INSTALL_EXTENSION,
# XLOG_TDE_WRITE_KEY_PROVIDER, XLOG_TDE_ADD_PRINCIPAL_KEY.
$node->safe_psql('postgres', "CREATE EXTENSION pg_tde;");
$node->safe_psql('postgres',
	"SELECT pg_tde_add_global_key_provider_file('file-keyring-wal', '$keydir/global.keys');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('server-key', 'file-keyring-wal');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'file-keyring-wal');"
);

my $end_lsn =
  $node->safe_psql('postgres', q{SELECT pg_current_wal_insert_lsn()});

$node->stop;

# Helper function to test various options.  Pass options as arguments.
# Output lines are returned as array. Copy of the func from pg_waldump_basic.pl
sub test_pg_waldump
{
	local $Test::Builder::Level = $Test::Builder::Level + 1;
	my @opts = @_;

	my (@cmd, $stdout, $stderr, $result, @lines);

	@cmd = (
		'pg_tde_waldump', '-k',
		$node->data_dir . '/pg_tde', '-p',
		$node->data_dir, '--start',
		$start_lsn, '--end',
		$end_lsn);
	push @cmd, @opts;
	$result = IPC::Run::run \@cmd, '>', \$stdout, '2>', \$stderr;
	ok($result, "pg_tde_waldump @opts: runs ok");
	is($stderr, '', "pg_tde_waldump @opts: no stderr");
	@lines = split /\n/, $stdout;
	ok(@lines > 0, "pg_tde_waldump @opts: some lines are output");
	return @lines;
}

my @lines;

# rmgr name and description are resolved, not left as the generic
# "custom140" / "UNKNOWN" output.
@lines = test_pg_waldump;
ok((grep { /^rmgr: pg_tde\b/ } @lines), 'pg_tde rmgr lines are present');
is(scalar(grep { /^rmgr: custom140\b/ } @lines),
	0, 'no unresolved custom140 rmgr lines');
is(scalar(grep { /^rmgr: pg_tde\b.*\bdesc: UNKNOWN\b/ } @lines),
	0, 'no unresolved UNKNOWN description for pg_tde records');
ok((grep { /^rmgr: pg_tde\b.*\bdesc: INSTALL_EXTENSION\b/ } @lines),
	'INSTALL_EXTENSION record is described');
ok((grep { /^rmgr: pg_tde\b.*\bdesc: WRITE_KEY_PROVIDER\b/ } @lines),
	'WRITE_KEY_PROVIDER record is described');
ok((grep { /^rmgr: pg_tde\b.*\bdesc: ADD_PRINCIPAL_KEY\b/ } @lines),
	'ADD_PRINCIPAL_KEY record is described');

# --rmgr=list includes the pg_tde resource manager by name.
{
	my ($stdout, $stderr);
	my $result = IPC::Run::run [ 'pg_tde_waldump', '--rmgr', 'list' ], '>',
	  \$stdout, '2>', \$stderr;
	ok($result, 'pg_tde_waldump --rmgr=list runs ok');
	like($stdout, qr/^pg_tde$/m, 'pg_tde is listed as a known rmgr');
}

# Filtering by the friendly name "pg_tde" only returns pg_tde lines, and
# matches the set of lines returned when filtering by the legacy
# "custom140" name.
@lines = test_pg_waldump('--rmgr', 'pg_tde');
ok(@lines > 0, 'at least one pg_tde record found when filtering by name');
is(scalar(grep { !/^rmgr: pg_tde\b/ } @lines),
	0, 'only pg_tde lines with --rmgr=pg_tde');

my @lines_legacy = test_pg_waldump('--rmgr', 'custom140');
is(scalar(grep { !/^rmgr: pg_tde\b/ } @lines_legacy),
	0, 'only pg_tde lines with legacy --rmgr=custom140');
is_deeply(\@lines, \@lines_legacy,
	'--rmgr=pg_tde and --rmgr=custom140 select the same records');

done_testing();
