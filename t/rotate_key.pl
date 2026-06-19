use strict;
use warnings FATAL => 'all';
use PostgreSQL::Test::Cluster;
use PostgreSQL::Test::Utils;
use Test::More;

my ($stdout, $stderr);

my $keydir = PostgreSQL::Test::Utils::tempdir;

my $node = PostgreSQL::Test::Cluster->new('main');
$node->init;
$node->append_conf('postgresql.conf', "shared_preload_libraries = 'pg_tde'");
$node->start;

$node->safe_psql(
	'postgres', qq(
	CREATE EXTENSION pg_tde;
	SELECT pg_tde_add_database_key_provider_file('file-vault', '$keydir/db1.keys');
	SELECT pg_tde_add_database_key_provider_file('file-2', '$keydir/db2.keys');
	SELECT pg_tde_add_global_key_provider_file('file-2', '$keydir/global2.keys');
	SELECT pg_tde_add_global_key_provider_file('file-3', '$keydir/global3.keys');
));

$stdout = $node->safe_psql('postgres',
	'SELECT pg_tde_list_all_database_key_providers();');
is( $stdout,
	qq((1,file-vault,file,"{""path"" : ""$keydir/db1.keys""}")\n(2,file-2,file,"{""path"" : ""$keydir/db2.keys""}")),
	'lists all database providers');

$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_database_key_provider('test-db-key', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('test-db-key', 'file-vault');

	CREATE TABLE test_enc (id SERIAL, k INTEGER, PRIMARY KEY (id)) USING tde_heap;
	INSERT INTO test_enc (k) VALUES (5), (6);
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can read data');

# Rotate key
$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_database_key_provider('rotated-key1', 'file-vault');
	SELECT pg_tde_set_key_using_database_key_provider('rotated-key1', 'file-vault');
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

$node->restart;

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '1|file-vault|rotated-key1', 'key changed');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

# Again rotate key
$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_database_key_provider('rotated-key2', 'file-2');
	SELECT pg_tde_set_key_using_database_key_provider('rotated-key2', 'file-2');
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

$node->restart;

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '2|file-2|rotated-key2', 'key changed');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

# Again rotate key
$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_global_key_provider('rotated-key', 'file-3');
	SELECT pg_tde_set_key_using_global_key_provider('rotated-key', 'file-3');
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

$node->restart;

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '-2|file-3|rotated-key', 'key changed');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

# TODO: add method to query current info
# And maybe debug tools to show what's in a file keyring?

# Again rotate key
$node->safe_psql(
	'postgres', qq(
	SELECT pg_tde_create_key_using_global_key_provider('rotated-keyX', 'file-2');
	SELECT pg_tde_set_key_using_global_key_provider('rotated-keyX', 'file-2');
));

$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

$node->restart;

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '-1|file-2|rotated-keyX', 'key changed');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');
$stdout = $node->safe_psql('postgres', 'SELECT * FROM test_enc ORDER BY id;');
is($stdout, "1|5\n2|6", 'can still read data');

$node->safe_psql('postgres',
	'ALTER SYSTEM SET pg_tde.inherit_global_providers = off;');

# Things still work after a restart
$node->restart;

# But now can't be changed to another global provider
(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_create_key_using_global_key_provider('rotated-keyX2', 'file-2');"
);
like(
	$stderr,
	qr/ERROR:  usage of global key providers is disabled/,
	'not allowed to generate global keys');

(undef, undef, $stderr) = $node->psql('postgres',
	"SELECT pg_tde_set_key_using_global_key_provider('rotated-keyX2', 'file-2');"
);
like(
	$stderr,
	qr/ERROR:  usage of global key providers is disabled/,
	'not allowed to configure global keys');

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '-1|file-2|rotated-keyX', 'key did not change');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');

$node->safe_psql('postgres',
	"SELECT pg_tde_set_key_using_database_key_provider('rotated-key2', 'file-2');"
);

$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_key_info();');
is($stdout, '2|file-2|rotated-key2', 'key changed');
$stdout = $node->safe_psql('postgres',
	'SELECT provider_id, provider_name, key_name FROM pg_tde_server_key_info();'
);
is($stdout, '||', 'server key was not affected');

$node->safe_psql('postgres', 'DROP TABLE test_enc;');

$node->safe_psql('postgres',
	'ALTER SYSTEM RESET pg_tde.inherit_global_providers;');

$node->restart;

$node->safe_psql('postgres', 'DROP EXTENSION pg_tde CASCADE;');

$node->stop;

done_testing();
