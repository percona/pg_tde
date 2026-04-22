#!/usr/bin/perl

use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my $keyring_file = '/tmp/pg_tde_ondisk.per';
unlink($keyring_file) if -e $keyring_file;

my $node = PostgreSQL::Test::Cluster->new('ondisk');
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

# ============================================================
# Scenario A: encrypted tablespace, marker ABSENT on disk.
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE enc_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('enc_ts');
    CREATE TABLE t_enc (x text) TABLESPACE enc_ts;
    INSERT INTO t_enc VALUES ('MARKER_ENCRYPTED_0xDEADBEEF42');
    CHECKPOINT;
});

my $enc_relpath = $node->safe_psql('postgres',
	"SELECT pg_relation_filepath('t_enc');");
my $enc_file = $node->data_dir . '/' . $enc_relpath;

$node->stop('fast');

ok(-f $enc_file, "Scenario A: encrypted heap file exists at $enc_file");

my $enc_contents = slurp_file($enc_file);
unlike(
	$enc_contents,
	qr/MARKER_ENCRYPTED_0xDEADBEEF42/,
	'Scenario A: encrypted heap file does not contain plaintext marker');

$node->start;

my $read_enc =
  $node->safe_psql('postgres', "SELECT x FROM t_enc;");
is( $read_enc,
	'MARKER_ENCRYPTED_0xDEADBEEF42',
	'Scenario A: SELECT from encrypted table returns plaintext');

# ============================================================
# Scenario B: plain tablespace, marker PRESENT on disk.
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE plain_ts LOCATION '';
    -- intentionally NOT marked encrypted
    CREATE TABLE t_plain (x text) TABLESPACE plain_ts;
    INSERT INTO t_plain VALUES ('MARKER_PLAINTEXT_0xCAFEBABE42');
    CHECKPOINT;
});

my $plain_relpath = $node->safe_psql('postgres',
	"SELECT pg_relation_filepath('t_plain');");
my $plain_file = $node->data_dir . '/' . $plain_relpath;

$node->stop('fast');

ok(-f $plain_file, "Scenario B: plain heap file exists at $plain_file");

my $plain_contents = slurp_file($plain_file);
like(
	$plain_contents,
	qr/MARKER_PLAINTEXT_0xCAFEBABE42/,
	'Scenario B: plain heap file contains plaintext marker');

$node->start;

my $read_plain =
  $node->safe_psql('postgres', "SELECT x FROM t_plain;");
is( $read_plain,
	'MARKER_PLAINTEXT_0xCAFEBABE42',
	'Scenario B: SELECT from plain table returns plaintext');

# ============================================================
# Scenario C: mark -> unmark -> new data must be plaintext on disk.
# Guards against stale smgr cache carrying "encrypted" decision over
# after a decrypted-mark flip.
# ============================================================
$node->safe_psql(
	'postgres', qq{
    CREATE TABLESPACE mix_ts LOCATION '';
    SELECT pg_tde_mark_tablespace_encrypted('mix_ts');
    CREATE TABLE t_a (x text) TABLESPACE mix_ts;
    INSERT INTO t_a VALUES ('MARKER_MIX_A_INITIAL_ENCRYPTED');
    CHECKPOINT;
    DROP TABLE t_a;
    SELECT pg_tde_mark_tablespace_decrypted('mix_ts');
    CREATE TABLE t_b (x text) TABLESPACE mix_ts;
    INSERT INTO t_b VALUES ('MARKER_MIX_B_AFTER_UNMARK_PLAINTEXT');
    CHECKPOINT;
});

# Capture the NEW table's path AFTER the final INSERT/CHECKPOINT.
my $mix_relpath = $node->safe_psql('postgres',
	"SELECT pg_relation_filepath('t_b');");
my $mix_file = $node->data_dir . '/' . $mix_relpath;

$node->stop('fast');

ok(-f $mix_file, "Scenario C: post-unmark heap file exists at $mix_file");

my $mix_contents = slurp_file($mix_file);
like(
	$mix_contents,
	qr/MARKER_MIX_B_AFTER_UNMARK_PLAINTEXT/,
	'Scenario C: after unmark, new table writes plaintext to disk (no stale-cache bug)'
);

$node->start;

my $read_mix =
  $node->safe_psql('postgres', "SELECT x FROM t_b;");
is( $read_mix,
	'MARKER_MIX_B_AFTER_UNMARK_PLAINTEXT',
	'Scenario C: SELECT from post-unmark table returns plaintext');

$node->stop;

unlink($keyring_file) if -e $keyring_file;

done_testing();
