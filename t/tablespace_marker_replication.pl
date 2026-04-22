#!/usr/bin/perl

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keyring_file = '/tmp/pg_tde_tsmarker_repl.per';
unlink($keyring_file) if -e $keyring_file;

my $primary = PostgreSQL::Test::Cluster->new('primary');
$primary->init(allows_streaming => 1);
$primary->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$primary->append_conf('postgresql.conf', 'allow_in_place_tablespaces = true');
$primary->start;

$primary->safe_psql(
	'postgres', qq{
    CREATE EXTENSION pg_tde;
    SELECT pg_tde_add_database_key_provider_file('fv', '$keyring_file');
    SELECT pg_tde_create_key_using_database_key_provider('k','fv');
    SELECT pg_tde_set_key_using_database_key_provider('k','fv');
});

$primary->backup('basebackup');

my $standby = PostgreSQL::Test::Cluster->new('standby');
$standby->init_from_backup($primary, 'basebackup', has_streaming => 1);
$standby->start;

# ============================================================
# Scenario A: mark encrypted on primary -> standby heap file
# has no plaintext marker.
# ============================================================
$primary->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE enc_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('enc_ts');
    CREATE TABLE t_enc (x text) TABLESPACE enc_ts;
    INSERT INTO t_enc VALUES ('MARKER_ENC_REPL_0xFEEDFACE01');
    CHECKPOINT;
});

$primary->wait_for_catchup($standby);

my $enc_relpath =
  $primary->safe_psql('postgres', "SELECT pg_relation_filepath('t_enc');");
# On the standby, a replayed checkpoint may not have flushed the buffer yet
# even though the WAL arrived. Force a restartpoint so the heap page hits disk.
$standby->safe_psql('postgres', 'CHECKPOINT;');

my $standby_enc_file = $standby->data_dir . '/' . $enc_relpath;
ok(-f $standby_enc_file,
	"Scenario A: standby replayed encrypted heap file at $standby_enc_file");

my $standby_enc_contents = slurp_file($standby_enc_file);
unlike(
	$standby_enc_contents,
	qr/MARKER_ENC_REPL_0xFEEDFACE01/,
	'Scenario A: standby heap file does not contain plaintext marker');

# ============================================================
# Scenario B: mark decrypted on primary -> standby heap file
# contains the plaintext marker.
# ============================================================
$primary->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE plain_ts LOCATION '';
    -- not marked encrypted
    CREATE TABLE t_plain (x text) TABLESPACE plain_ts;
    INSERT INTO t_plain VALUES ('MARKER_PLAIN_REPL_0xCAFEBABE02');
    CHECKPOINT;
});

$primary->wait_for_catchup($standby);

my $plain_relpath =
  $primary->safe_psql('postgres', "SELECT pg_relation_filepath('t_plain');");
$standby->safe_psql('postgres', 'CHECKPOINT;');

my $standby_plain_file = $standby->data_dir . '/' . $plain_relpath;
ok(-f $standby_plain_file,
	"Scenario B: standby replayed plain heap file at $standby_plain_file");

my $standby_plain_contents = slurp_file($standby_plain_file);
like(
	$standby_plain_contents,
	qr/MARKER_PLAIN_REPL_0xCAFEBABE02/,
	'Scenario B: standby heap file contains plaintext marker');

# ============================================================
# Scenario C: DROP TABLESPACE on primary -> standby's list file
# no longer contains the OID.
# ============================================================
$primary->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE drop_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('drop_ts');
});

my $drop_oid = $primary->safe_psql('postgres',
	"SELECT oid FROM pg_tablespace WHERE spcname='drop_ts';");
ok($drop_oid =~ /^\d+$/, "Scenario C: resolved drop_ts OID=$drop_oid");

$primary->wait_for_catchup($standby);

my $list_path = '/pg_tde/encrypted_tablespaces.lst';
my $standby_list_before = slurp_file($standby->data_dir . $list_path);
like(
	$standby_list_before,
	qr/\Q@{[ pack('V', $drop_oid) ]}\E/,
	'Scenario C: standby list file contains OID before DROP');

$primary->safe_psql('postgres', 'DROP TABLESPACE drop_ts;');

$primary->wait_for_catchup($standby);

my $standby_list_after = slurp_file($standby->data_dir . $list_path);
unlike(
	$standby_list_after,
	qr/\Q@{[ pack('V', $drop_oid) ]}\E/,
	'Scenario C: standby list file no longer contains OID after DROP');

# Structural check: parse the 16-byte header + oid array and confirm
# $drop_oid is not in the array at all.
sub parse_list_file
{
	my ($path) = @_;
	my $raw = slurp_file($path);
	my ($magic, $version, $count, $reserved) = unpack('VVVV', substr($raw, 0, 16));
	die "bad magic" unless $magic == 0x54444553;
	die "bad version" unless $version == 1;
	my @oids = unpack('V*', substr($raw, 16, 4 * $count));
	die "count mismatch" unless scalar(@oids) == $count;
	return \@oids;
}

my $parsed = parse_list_file($standby->data_dir . $list_path);
ok(!(grep { $_ == $drop_oid } @$parsed),
	"Scenario C: parsed standby list file has no $drop_oid entry");

# ============================================================
# Scenario D: a DROP TABLESPACE that fails at validation (non-empty)
# must NOT silently remove the encryption mark on primary or replica.
# Regression for C1: the drop hook used to run BEFORE
# standard_ProcessUtility, so the decrypt-mark WAL record was flushed
# even when the DROP subsequently failed.
# ============================================================
$primary->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE keep_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('keep_ts');
    CREATE TABLE t_keep (x text) TABLESPACE keep_ts;
    INSERT INTO t_keep VALUES ('MARKER_KEEP_0xBEEFFACE04');
    CHECKPOINT;
});
$primary->wait_for_catchup($standby);

my $keep_oid = $primary->safe_psql('postgres',
	"SELECT oid FROM pg_tablespace WHERE spcname='keep_ts';");
ok($keep_oid =~ /^\d+$/, "Scenario D: resolved keep_ts OID=$keep_oid");

# Try to DROP the tablespace while non-empty — should fail.
my ($ret, $stdout, $stderr) =
  $primary->psql('postgres', 'DROP TABLESPACE keep_ts;');
isnt($ret, 0, 'Scenario D: DROP TABLESPACE fails on non-empty tablespace');

# Confirm on the primary: a fresh table in keep_ts is still flagged encrypted.
my $still_marked = $primary->safe_psql(
	'postgres', qq{
    CREATE TABLE t_keep_probe (x text) TABLESPACE keep_ts;
    SELECT pg_tde_is_encrypted('t_keep_probe');
});
is($still_marked, 't',
	'Scenario D: mark survives failed DROP on primary');

$primary->wait_for_catchup($standby);

# The list file on the standby must still contain the OID.
my $standby_list_after_fail = slurp_file($standby->data_dir . $list_path);
like(
	$standby_list_after_fail,
	qr/\Q@{[ pack('V', $keep_oid) ]}\E/,
	'Scenario D: standby list file still contains OID after failed DROP');

my $parsed_after_fail = parse_list_file($standby->data_dir . $list_path);
ok((grep { $_ == $keep_oid } @$parsed_after_fail),
	"Scenario D: parsed standby list file still has $keep_oid entry");

# Clean up Scenario D artifacts.
$primary->safe_psql(
	'postgres', qq{
    DROP TABLE t_keep_probe;
    DROP TABLE t_keep;
    DROP TABLESPACE keep_ts;
});
$primary->wait_for_catchup($standby);

$standby->stop;
$primary->stop;

unlink($keyring_file) if -e $keyring_file;

done_testing();
