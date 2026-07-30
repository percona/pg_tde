# Check that WAL archiving works when pg_wal is a symlink.
use strict;
use warnings FATAL => 'all';
use File::Copy;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

# Test CLI tools directly

# Wal archiving uses linux specific tmpfs mount point for temporary files.
if ($^O ne 'linux')
{
	plan skip_all => 'tde wal_archiving works only on Linux';
	exit 0;
}

my $keydir = PostgreSQL::Test::Utils::tempdir;
my $wal_dir = PostgreSQL::Test::Utils::tempdir;

# Test archive_command

my $primary = PostgreSQL::Test::Cluster->new('primary');
my $archive_dir = $primary->archive_dir;
$primary->init(allows_streaming => 1);
$primary->append_conf('postgresql.conf',
	"shared_preload_libraries = 'pg_tde'");
$primary->append_conf('postgresql.conf', "wal_level = 'replica'");
$primary->append_conf('postgresql.conf', "autovacuum = off");
$primary->append_conf('postgresql.conf', "checkpoint_timeout = 1h");
$primary->append_conf('postgresql.conf', "archive_mode = on");
$primary->append_conf('postgresql.conf',
	"archive_command = 'pg_tde_archive_decrypt %f %p \"cp %%p $archive_dir/%%f\"'"
);

my $test_primary_datadir = $primary->data_dir;

# Turn pg_wal into a symlink
print("moving $test_primary_datadir/pg_wal to $wal_dir\n");
move("$test_primary_datadir/pg_wal", $wal_dir)
  or BAIL_OUT("cannot move pg_wal: $!");
dir_symlink($wal_dir, "$test_primary_datadir/pg_wal")
  or BAIL_OUT("cannot create a symlink to pg_wal: $!");

$primary->start;

$primary->safe_psql('postgres', "CREATE EXTENSION pg_tde;");
$primary->safe_psql('postgres',
	"SELECT pg_tde_add_global_key_provider_file('keyring', '$keydir/global.keys');"
);
$primary->safe_psql('postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('server-key', 'keyring');"
);
$primary->safe_psql('postgres',
	"SELECT pg_tde_set_server_key_using_global_key_provider('server-key', 'keyring');"
);

$primary->append_conf('postgresql.conf', "pg_tde.wal_encrypt = on");
$primary->restart;

# "-X none" ensures no WAL in the backup; hence, it must be restored from the archive
$primary->backup('backup1', backup_options => [ '-X', 'none' ]);

$primary->safe_psql('postgres', "CREATE TABLE t1 AS SELECT 'foobar' AS x");

$primary->stop;

ok( !$primary->log_contains('pg_tde_archive_decrypt'),
	'verify there are no pg_tde_archive_decrypt messages in log');

my $replica = PostgreSQL::Test::Cluster->new('replica');
$replica->init_from_backup($primary, 'backup1');
$replica->append_conf('postgresql.conf',
	"restore_command = 'pg_tde_restore_encrypt %f %p \"cp $archive_dir/%%f %%p\"'"
);
$replica->set_standby_mode;
$replica->start;

$replica->wait_for_log("waiting for WAL to become available");

$replica->promote;

# Check that data restored from the WAL archive is readable
my $result = $replica->safe_psql('postgres', 'SELECT * FROM t1');
is($result, "foobar", 'data is readable after restore');

$replica->stop;

done_testing();
