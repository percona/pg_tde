#!/usr/bin/perl

use strict;
use warnings;
use File::Basename;
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;
use lib 't';
use pgtde;

PGTDE::setup_files_dir(basename($0));

my $keyring_file = '/tmp/tablespace_prototype.per';
unlink($keyring_file);

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');

$node->safe_psql('postgres',
	"SELECT pg_tde_add_database_key_provider_file('file-vault', '$keyring_file');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-vault');"
);
$node->safe_psql('postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-vault');"
);

# Real (non-in-place) tablespace directory.
my $tblspc_path = PostgreSQL::Test::Utils::tempdir_short();

$node->safe_psql('postgres',
	"CREATE TABLESPACE enc_ts LOCATION '$tblspc_path';");
$node->safe_psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('enc_ts');");

$node->safe_psql('postgres',
	'CREATE TABLE t_enc (x int, note text) TABLESPACE enc_ts;');
$node->safe_psql('postgres',
	'CREATE TABLE t_plain (x int, note text);');

my $row_count = 200;
$node->safe_psql('postgres',
	"INSERT INTO t_enc SELECT g, 'NEEDLE-' || g FROM generate_series(1, $row_count) g;"
);
$node->safe_psql('postgres',
	"INSERT INTO t_plain SELECT g, 'NEEDLE-' || g FROM generate_series(1, $row_count) g;"
);

$node->safe_psql('postgres', 'CHECKPOINT;');

# Capture paths while the cluster is up.
my $enc_rel_path = $node->safe_psql('postgres',
	"SELECT pg_relation_filepath('t_enc');");
my $plain_rel_path = $node->safe_psql('postgres',
	"SELECT pg_relation_filepath('t_plain');");

my $enc_abs_path = $node->data_dir . '/' . $enc_rel_path;
my $plain_abs_path = $node->data_dir . '/' . $plain_rel_path;

# Clean shutdown so nothing remains buffered.
$node->stop;

ok(-f $enc_abs_path,
	"encrypted table backing file exists at $enc_abs_path");
ok(-f $plain_abs_path,
	"plain table backing file exists at $plain_abs_path");

sub count_needles
{
	my ($file) = @_;

	open(my $fh, '<:raw', $file) or die "cannot open $file: $!";
	my $count = 0;
	my $needle = 'NEEDLE-';
	my $buf;
	my $carry = '';
	while (read($fh, $buf, 65536))
	{
		my $chunk = $carry . $buf;
		my $pos = 0;
		while ((my $idx = index($chunk, $needle, $pos)) >= 0)
		{
			$count++;
			$pos = $idx + length($needle);
		}
		# Keep the tail so a needle crossing a chunk boundary is still found.
		$carry = substr($chunk, -(length($needle) - 1));
	}
	close($fh);
	return $count;
}

my $plain_hits = count_needles($plain_abs_path);
my $enc_hits = count_needles($enc_abs_path);

cmp_ok($plain_hits, '>', 0,
	"control: plaintext NEEDLE appears in plain-tablespace file ($plain_hits hits)"
);
is($enc_hits, 0,
	"encrypted tablespace file contains no NEEDLE plaintext ($enc_hits hits)"
);

# Restart and verify transparent decryption works.
$node->start;

my $live_count = $node->safe_psql('postgres',
	"SELECT count(*) FROM t_enc WHERE note LIKE 'NEEDLE-%';");
is($live_count, $row_count,
	"after restart, SELECT returns all $row_count rows from encrypted table");

$node->safe_psql('postgres', 'DROP TABLE t_enc;');
$node->safe_psql('postgres', 'DROP TABLE t_plain;');
$node->safe_psql('postgres', 'DROP TABLESPACE enc_ts;');

# In-place tablespaces (LOCATION '') require this dev-only GUC.
$node->safe_psql('postgres', "ALTER SYSTEM SET allow_in_place_tablespaces = on;");
$node->safe_psql('postgres', "SELECT pg_reload_conf();");

# Capacity: 128 marks succeed, 129th errors cleanly.
for my $i (1..128) {
	$node->safe_psql('postgres', "CREATE TABLESPACE cap_$i LOCATION '';");
	$node->safe_psql('postgres', "SELECT pg_tde_mark_tablespace_encrypted('cap_$i');");
}
$node->safe_psql('postgres', "CREATE TABLESPACE cap_overflow LOCATION '';");
my ($ret, $out, $err) = $node->psql('postgres',
	"SELECT pg_tde_mark_tablespace_encrypted('cap_overflow');");
isnt($ret, 0, 'mark errors at capacity');
like($err, qr/more than 128 tablespaces/, 'clear error');

# Confirm the list file was not partially written (still has exactly 128 oids).
# Read the list file header to count.
my $list_file = $node->data_dir . '/pg_tde/encrypted_tablespaces.lst';
open my $fh, '<:raw', $list_file or die;
my $hdr;
read($fh, $hdr, 16);
close $fh;
my ($magic, $ver, $count) = unpack('V3', $hdr);
is($count, 128, 'no partial write on overflow');

# cleanup
$node->safe_psql('postgres', "DROP TABLESPACE cap_overflow;");
for my $i (reverse 1..128) {
	$node->safe_psql('postgres',
		"SELECT pg_tde_mark_tablespace_decrypted('cap_$i'); DROP TABLESPACE cap_$i;");
}

# DROP TABLESPACE cleanup: marked OID disappears from list file post-restart.
$node->safe_psql('postgres', qq{
	CREATE TABLESPACE drop_ts LOCATION '';
	SELECT pg_tde_mark_tablespace_encrypted('drop_ts');
});
my $drop_oid = $node->safe_psql('postgres',
	"SELECT oid FROM pg_tablespace WHERE spcname='drop_ts';");
$node->safe_psql('postgres', "DROP TABLESPACE drop_ts;");
$node->restart;

my $list_bytes = slurp_file($node->data_dir . '/pg_tde/encrypted_tablespaces.lst');
my $oid_packed = pack('V', $drop_oid);
unlike($list_bytes, qr/\Q$oid_packed\E/,
	 'OID cleaned from list file after DROP');

$node->safe_psql('postgres', 'DROP EXTENSION pg_tde;');

$node->stop;

unlink($keyring_file);

done_testing();
