#!/usr/bin/perl

use strict;
use warnings;
use Test::More;
use lib 't';
use CosmianKms;
use PostgreSQL::Test::Utils;
use PostgreSQL::Test::Cluster;

my $cosmian_bin = CosmianKms::find_binary();
unless ($cosmian_bin)
{
	if ($ENV{PG_TEST_REQUIRE_COSMIAN_KMS})
	{
		BAIL_OUT("cosmian_kms required but not found "
			  . "(PG_TEST_REQUIRE_COSMIAN_KMS=1 set)");
	}
	plan skip_all =>
	  "cosmian_kms not on PATH; set COSMIAN_KMS_BIN to override";
}

# ---------------------------------------------------------------------------
# Cosmian + cert setup.
# ---------------------------------------------------------------------------
my $tmpdir = PostgreSQL::Test::Utils::tempdir();
CosmianKms::gen_certs($tmpdir);
my ($cosmian_h, $kmip_port) =
  CosmianKms::start_with_free_port($cosmian_bin, $tmpdir);

END
{
	CosmianKms::stop($cosmian_h);
}

# ---------------------------------------------------------------------------
# PostgreSQL cluster.
# ---------------------------------------------------------------------------
my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql('postgres', 'CREATE EXTENSION pg_tde;');

# Provider + key + encrypted table.
$node->safe_psql('postgres', <<SQL);
SELECT pg_tde_add_database_key_provider_kmip(
    'kmip-prov', '127.0.0.1', $kmip_port,
    '$tmpdir/client.pem', '$tmpdir/client.key', '$tmpdir/ca.pem');
SELECT pg_tde_create_key_using_database_key_provider(
    'kmip-key', 'kmip-prov');
SELECT pg_tde_set_key_using_database_key_provider(
    'kmip-key', 'kmip-prov');
CREATE TABLE test_enc(
    id SERIAL, k INTEGER NOT NULL, PRIMARY KEY(id)) USING tde_heap;
INSERT INTO test_enc(k) VALUES (1), (2), (3);
SQL

is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3", 'encrypted insert round-trip');

# Restart → cold cache → KMIP re-fetch.
$node->restart;
is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3", 'decrypts after restart (KMIP re-fetch)');

# Key rotation + post-rotation insert.
$node->safe_psql('postgres', <<SQL);
SELECT pg_tde_create_key_using_database_key_provider(
    'kmip-key2', 'kmip-prov');
SELECT pg_tde_set_key_using_database_key_provider(
    'kmip-key2', 'kmip-prov');
INSERT INTO test_enc(k) VALUES (4), (5);
SQL

is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3\n4\n5", 'rows readable across key rotation');

# Restart after rotation.
$node->restart;
is($node->safe_psql('postgres', 'SELECT k FROM test_enc ORDER BY id;'),
	"1\n2\n3\n4\n5", 'rows readable after restart following rotation');

$node->stop;

done_testing();
