#!/usr/bin/perl

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keyring_file = '/tmp/pg_tde_persist.per';
unlink($keyring_file) if -e $keyring_file;

my $node = PostgreSQL::Test::Cluster->new('persist');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->append_conf('postgresql.conf', 'allow_in_place_tablespaces = true');
$node->start;

$node->safe_psql(
	'postgres', qq{
    CREATE EXTENSION pg_tde;
    SELECT pg_tde_add_database_key_provider_file('fv', '$keyring_file');
    SELECT pg_tde_create_key_using_database_key_provider('k','fv');
    SELECT pg_tde_set_key_using_database_key_provider('k','fv');
});

my $list_file = $node->data_dir . '/pg_tde/encrypted_tablespaces.lst';

# ============================================================
# Scenario 1: clean stop/start
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE s1_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('s1_ts');
});

$node->stop('fast');
$node->start;

my $is_enc = $node->safe_psql(
	'postgres', qq{
    CREATE TABLE s1_probe (x int) TABLESPACE s1_ts;
    SELECT pg_tde_is_encrypted('s1_probe');
});
is($is_enc, 't', 'Scenario 1: mark survives clean stop/start');

$node->safe_psql(
	'postgres', qq{
    DROP TABLE s1_probe;
    SELECT pg_tde_mark_tablespace_decrypted('s1_ts');
    DROP TABLESPACE s1_ts;
});

# ============================================================
# Scenario 2: immediate stop (crash) + recovery
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE s2_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('s2_ts');
});
$node->stop('immediate');    # simulates crash
$node->start;                # triggers WAL replay

$is_enc = $node->safe_psql(
	'postgres', qq{
    CREATE TABLE s2_probe (x int) TABLESPACE s2_ts;
    SELECT pg_tde_is_encrypted('s2_probe');
});
is($is_enc, 't',
	'Scenario 2: mark survives immediate stop + crash recovery');

$node->safe_psql(
	'postgres', qq{
    DROP TABLE s2_probe;
    SELECT pg_tde_mark_tablespace_decrypted('s2_ts');
    DROP TABLESPACE s2_ts;
});

# ============================================================
# Scenario 3: FATAL on corrupt list file
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE s3_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('s3_ts');
});
$node->stop('fast');

# Clobber the 4-byte magic at the head of the list file.
{
	open my $fh, '+<:raw', $list_file or die "open $list_file: $!";
	seek $fh, 0, 0;
	print $fh 'XXXX';
	close $fh;
}

# Truncate the existing log so we only scan messages from this start attempt.
{
	open my $lfh, '>', $node->logfile or die "truncate logfile: $!";
	close $lfh;
}

my $ret = $node->start(fail_ok => 1);
is($ret, 0, 'Scenario 3: postmaster refuses to start on corrupt marker file');

my $log = slurp_file($node->logfile);
like(
	$log,
	qr/has bad header/i,
	'Scenario 3: log explains the corruption');

# Repair for subsequent scenarios: delete the corrupt file so the cluster
# starts with an empty list.
unlink $list_file;
$node->start;

# s3_ts is empty (nothing was ever created in it); drop it now that we are
# up again. It is no longer on the list after the unlink.
$node->safe_psql('postgres', 'DROP TABLESPACE s3_ts;');

# ============================================================
# Scenario 4: missing file -> empty list, cluster starts cleanly
# ============================================================
$node->stop('fast');
unlink $list_file if -e $list_file;
$node->start;

$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE s4_ts LOCATION '';
    CREATE TABLE s4_probe (x int) TABLESPACE s4_ts;
});
my $is_plain = $node->safe_psql('postgres',
	"SELECT pg_tde_is_encrypted('s4_probe');");
is($is_plain, 'f', 'Scenario 4: missing list file means empty state');

$node->safe_psql(
	'postgres', qq{
    DROP TABLE s4_probe;
    DROP TABLESPACE s4_ts;
});

# ============================================================
# Scenario 5: pg_upgrade carry-over (on-disk format portability)
#
# pg_tde_upgrade (src/bin/pg_tde_upgrade.c) copies $PGDATA/pg_tde/ verbatim
# into the new cluster. Here we verify that the list file has a sound
# on-disk layout so the receiving cluster will load it successfully. A
# full end-to-end pg_upgrade test is covered by t/pg_tde_upgrade.pl.
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE s5_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('s5_ts');
});

my $stat_size = -s $list_file;
cmp_ok($stat_size, '>', 16,
	'Scenario 5: list file has body after mark');

open my $fh, '<:raw', $list_file or die "open $list_file: $!";
my $hdr;
read($fh, $hdr, 16);
close $fh;
my ($magic, $ver, $count, $res) = unpack('VVVV', $hdr);
is($magic, 0x54444553,
	'Scenario 5: list file magic readable for upgrade');
is($ver, 1, 'Scenario 5: list file version readable for upgrade');
cmp_ok($count, '>', 0,
	'Scenario 5: list file has at least one OID for upgrade');

$node->safe_psql(
	'postgres', qq{
    SELECT pg_tde_mark_tablespace_decrypted('s5_ts');
    DROP TABLESPACE s5_ts;
});

$node->stop;

unlink($keyring_file) if -e $keyring_file;

done_testing();
