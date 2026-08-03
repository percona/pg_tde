\! rm -f '/tmp/pg_tde_keyring.per'

CREATE EXTENSION pg_tde;
SELECT pg_tde_add_database_key_provider_file('database_keyring_provider','/tmp/pg_tde_keyring.per');
SELECT pg_tde_create_key_using_database_key_provider('table_key','database_keyring_provider');
SELECT pg_tde_set_key_using_database_key_provider('table_key','database_keyring_provider');
CREATE TABLE IF NOT EXISTS partitioned_table (
    id SERIAL,
    data TEXT,
    created_at DATE NOT NULL,
    PRIMARY KEY (id, created_at)
    ) PARTITION BY RANGE (created_at) USING tde_heap;

CREATE TABLE partition_q1_2024 PARTITION OF partitioned_table FOR VALUES FROM ('2024-01-01') TO ('2024-04-01') USING tde_heap;
CREATE TABLE partition_q2_2024 PARTITION OF partitioned_table FOR VALUES FROM ('2024-04-01') TO ('2024-07-01') USING heap;
CREATE TABLE partition_q3_2024 PARTITION OF partitioned_table FOR VALUES FROM ('2024-07-01') TO ('2024-10-01') USING tde_heap;
CREATE TABLE partition_q4_2024 PARTITION OF partitioned_table FOR VALUES FROM ('2024-10-01') TO ('2025-01-01') USING heap;

SELECT pg_tde_is_encrypted('partitioned_table');
SELECT pg_tde_is_encrypted('partition_q1_2024');
SELECT pg_tde_is_encrypted('partition_q2_2024');
SELECT pg_tde_is_encrypted('partition_q3_2024');
SELECT pg_tde_is_encrypted('partition_q4_2024');

ALTER TABLE partitioned_table SET ACCESS METHOD heap;
ALTER TABLE partition_q1_2024 SET ACCESS METHOD heap;
ALTER TABLE partition_q2_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partition_q3_2024 SET ACCESS METHOD heap;
ALTER TABLE partition_q4_2024 SET ACCESS METHOD tde_heap;

SELECT pg_tde_is_encrypted('partitioned_table');
SELECT pg_tde_is_encrypted('partition_q1_2024');
SELECT pg_tde_is_encrypted('partition_q2_2024');
SELECT pg_tde_is_encrypted('partition_q3_2024');
SELECT pg_tde_is_encrypted('partition_q4_2024');

-- Does not care about parent AM as long as all children with storage use the same
ALTER TABLE partition_q1_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partition_q2_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partition_q3_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partition_q4_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partitioned_table SET ACCESS METHOD heap;

DROP TABLE partitioned_table;

-- Partition inherits encryption status from parent table if default is heap and parent is tde_heap
SET default_table_access_method = "heap";
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a) USING tde_heap;
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9);
SELECT pg_tde_is_encrypted('partition_child');
DROP TABLE partition_parent;
RESET default_table_access_method;

-- Partition inherits encryption status from parent table if default is tde_heap and parent is heap
SET default_table_access_method = "tde_heap";
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a) USING heap;
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9);
SELECT pg_tde_is_encrypted('partition_child');
DROP TABLE partition_parent;
RESET default_table_access_method;

-- Partition uses default access method to determine encryption status if neither parent nor child have an access method set
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
SET default_table_access_method = "tde_heap";
CREATE TABLE partition_child_tde PARTITION OF partition_parent FOR VALUES FROM (0) TO (9);
SELECT pg_tde_is_encrypted('partition_child_tde');
SET default_table_access_method = "heap";
CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (10) TO (19);
SELECT pg_tde_is_encrypted('partition_child_heap');
DROP TABLE partition_parent;
RESET default_table_access_method;

-- Enforce encryption GUC is respected when creating partitions even if parent is plain text
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a) USING heap;
SET pg_tde.enforce_encryption = on;
CREATE TABLE partition_child_inherit PARTITION OF partition_parent FOR VALUES FROM (0) TO (10);
CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (11) TO (20) USING heap;
CREATE TABLE partition_child_tde_heap PARTITION OF partition_parent FOR VALUES FROM (11) TO (20) USING tde_heap;
SELECT pg_tde_is_encrypted('partition_child_tde_heap');
DROP TABLE partition_parent;
RESET pg_tde.enforce_encryption;

-- Does not change encryption of child tables when rewriting and changing AM
CREATE TABLE partition_parent (a int, b int) PARTITION BY RANGE (a) USING tde_heap;
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING tde_heap;
SELECT pg_tde_is_encrypted('partition_child');
ALTER TABLE partition_parent SET ACCESS METHOD heap, ALTER b TYPE bigint;
SELECT relname, amname FROM pg_class JOIN pg_am ON pg_am.oid = pg_class.relam WHERE relname IN ('partition_parent', 'partition_child') ORDER BY relname;
SELECT pg_tde_is_encrypted('partition_child');
DROP TABLE partition_parent;

-- Partitioned indexes should be encrypted
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING tde_heap;
CREATE INDEX ON partition_parent (a);
SELECT pg_tde_is_encrypted('partition_parent_a_idx'); -- Also check that the parent index is NULL
SELECT pg_tde_is_encrypted('partition_child_a_idx');
DROP TABLE partition_parent;

-- Partitioned indexes should be not encrypted with heap
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING heap;
CREATE INDEX ON partition_parent (a);
SELECT pg_tde_is_encrypted('partition_child_a_idx');
DROP TABLE partition_parent;

-- We refuse to create an index when the inheritance heirarchy has mixed statuses
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
CREATE TABLE partition_child_heap PARTITION OF partition_parent FOR VALUES FROM (0) TO (9) USING heap;
CREATE TABLE partition_child_tde_heap PARTITION OF partition_parent FOR VALUES FROM (10) TO (19) USING tde_heap;
CREATE INDEX ON partition_parent (a);
DROP TABLE partition_parent;

-- Index should also be encrypted for new partitionins
CREATE TABLE partition_parent (a int) PARTITION BY RANGE (a);
CREATE INDEX ON partition_parent (a);
CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (10) TO (19) USING tde_heap;
SELECT pg_tde_is_encrypted('partition_child_a_idx');
DROP TABLE partition_parent;

-- Split/merge should behave like creating a new partition

CREATE TABLE partitioned_table_plain (
    id int,
    data text,
    created_at date,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at) USING heap;

CREATE TABLE partition_q1q2_2024 PARTITION OF partitioned_table_plain FOR VALUES FROM ('2024-01-01') TO ('2024-07-01') USING tde_heap;
CREATE TABLE partition_q3q4_2024 PARTITION OF partitioned_table_plain FOR VALUES FROM ('2024-07-01') TO ('2025-01-01') USING heap;

ALTER TABLE partitioned_table_plain SPLIT PARTITION partition_q1q2_2024 INTO (
    PARTITION partition_q1_2024 FOR VALUES FROM ('2024-01-01') TO ('2024-04-01'),
    PARTITION partition_q2_2024 FOR VALUES FROM ('2024-04-01') TO ('2024-07-01')
);
ALTER TABLE partitioned_table_plain SPLIT PARTITION partition_q3q4_2024 INTO (
    PARTITION partition_q3_2024 FOR VALUES FROM ('2024-07-01') TO ('2024-10-01'),
    PARTITION partition_q4_2024 FOR VALUES FROM ('2024-10-01') TO ('2025-01-01')
);

SELECT pg_tde_is_encrypted('partition_q1_2024');
SELECT pg_tde_is_encrypted('partition_q2_2024');
SELECT pg_tde_is_encrypted('partition_q3_2024');
SELECT pg_tde_is_encrypted('partition_q4_2024');

ALTER TABLE partition_q3_2024 SET ACCESS METHOD tde_heap;

ALTER TABLE partitioned_table_plain MERGE PARTITIONS (partition_q1_2024, partition_q2_2024) INTO partition_q1q2_2024;
ALTER TABLE partitioned_table_plain MERGE PARTITIONS (partition_q3_2024, partition_q4_2024) INTO partition_q3q4_2024;

SELECT pg_tde_is_encrypted('partition_q1q2_2024');
SELECT pg_tde_is_encrypted('partition_q3q4_2024');

DROP TABLE partitioned_table_plain;

CREATE TABLE partitioned_table_enc (
    id int,
    data text,
    created_at date,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at) USING tde_heap;

CREATE TABLE partition_q1q2_2024 PARTITION OF partitioned_table_enc FOR VALUES FROM ('2024-01-01') TO ('2024-07-01') USING tde_heap;
CREATE TABLE partition_q3q4_2024 PARTITION OF partitioned_table_enc FOR VALUES FROM ('2024-07-01') TO ('2025-01-01') USING heap;

ALTER TABLE partitioned_table_enc SPLIT PARTITION partition_q1q2_2024 INTO (
    PARTITION partition_q1_2024 FOR VALUES FROM ('2024-01-01') TO ('2024-04-01'),
    PARTITION partition_q2_2024 FOR VALUES FROM ('2024-04-01') TO ('2024-07-01')
);
ALTER TABLE partitioned_table_enc SPLIT PARTITION partition_q3q4_2024 INTO (
    PARTITION partition_q3_2024 FOR VALUES FROM ('2024-07-01') TO ('2024-10-01'),
    PARTITION partition_q4_2024 FOR VALUES FROM ('2024-10-01') TO ('2025-01-01')
);

SELECT pg_tde_is_encrypted('partition_q1_2024');
SELECT pg_tde_is_encrypted('partition_q2_2024');
SELECT pg_tde_is_encrypted('partition_q3_2024');
SELECT pg_tde_is_encrypted('partition_q4_2024');

ALTER TABLE partition_q3_2024 SET ACCESS METHOD heap;

ALTER TABLE partitioned_table_enc MERGE PARTITIONS (partition_q1_2024, partition_q2_2024) INTO partition_q1q2_2024;
ALTER TABLE partitioned_table_enc MERGE PARTITIONS (partition_q3_2024, partition_q4_2024) INTO partition_q3q4_2024;

SELECT pg_tde_is_encrypted('partition_q1q2_2024');
SELECT pg_tde_is_encrypted('partition_q3q4_2024');

DROP TABLE partitioned_table_enc;

CREATE TABLE partitioned_table_default (
    id int,
    data text,
    created_at date,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE partition_q1q2_2024 PARTITION OF partitioned_table_default FOR VALUES FROM ('2024-01-01') TO ('2024-07-01') USING tde_heap;
CREATE TABLE partition_q3q4_2024 PARTITION OF partitioned_table_default FOR VALUES FROM ('2024-07-01') TO ('2025-01-01') USING heap;

SET default_table_access_method = 'tde_heap';
ALTER TABLE partitioned_table_default SPLIT PARTITION partition_q1q2_2024 INTO (
    PARTITION partition_q1_2024 FOR VALUES FROM ('2024-01-01') TO ('2024-04-01'),
    PARTITION partition_q2_2024 FOR VALUES FROM ('2024-04-01') TO ('2024-07-01')
);
RESET default_table_access_method;
ALTER TABLE partitioned_table_default SPLIT PARTITION partition_q3q4_2024 INTO (
    PARTITION partition_q3_2024 FOR VALUES FROM ('2024-07-01') TO ('2024-10-01'),
    PARTITION partition_q4_2024 FOR VALUES FROM ('2024-10-01') TO ('2025-01-01')
);

SELECT pg_tde_is_encrypted('partition_q1_2024');
SELECT pg_tde_is_encrypted('partition_q2_2024');
SELECT pg_tde_is_encrypted('partition_q3_2024');
SELECT pg_tde_is_encrypted('partition_q4_2024');

ALTER TABLE partition_q1_2024 SET ACCESS METHOD tde_heap;
ALTER TABLE partition_q3_2024 SET ACCESS METHOD heap;

ALTER TABLE partitioned_table_default MERGE PARTITIONS (partition_q1_2024, partition_q2_2024) INTO partition_q1q2_2024;
SET default_table_access_method = 'tde_heap';
ALTER TABLE partitioned_table_default MERGE PARTITIONS (partition_q3_2024, partition_q4_2024) INTO partition_q3q4_2024;
RESET default_table_access_method;

SELECT pg_tde_is_encrypted('partition_q1q2_2024');
SELECT pg_tde_is_encrypted('partition_q3q4_2024');

DROP TABLE partitioned_table_default;

DROP EXTENSION pg_tde;
