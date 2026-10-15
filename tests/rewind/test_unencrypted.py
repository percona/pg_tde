# pg_tde_rewind on a cluster without pg_tde loaded
import stormweaver.testing as st

from pgtde.node import TdeNode


# Target has WAL records beyond both the last checkpoint and the divergence
# point; pg_rewind used to ignore minRecoveryPoint and skip the rewind.
#
# Target WAL (TLI 2):
#   backup ... Checkpoint A ... INSERT 'rewind this'
#              (TLI 1 -> 2)
#              ^ last common checkpoint          ^ minRecoveryPoint
# Source WAL (TLI 3):
#   backup ... Checkpoint A ... Checkpoint B ... INSERT 'keep this'
#              (TLI 1 -> 2)     (TLI 2 -> 3)
def test_min_recovery_point(tde_node_factory):
    node_1 = tde_node_factory(
        "node_1",
        preload="",
        # allows_streaming in Cluster.pm init
        config={"wal_log_hints": "on", "wal_keep_size": "100 MB"},
    )
    node_1.safe_sql("""
        CREATE TABLE public.foo (t TEXT);
        CREATE TABLE public.bar (t TEXT);
        INSERT INTO public.bar VALUES ('in both');
    """)

    with (
        TdeNode.from_backup(node_1.basebackup(), node_1, name="node_2") as node_2,
        TdeNode.from_backup(node_1.basebackup(), node_1, name="node_3") as node_3,
    ):
        node_1.wait_for_catchup(node_3)

        # swap roles of node_1 and node_3, node_2 follows node_3
        node_1.stop(mode="fast")
        node_3.promote()
        node_1.rejoin_as_standby(node_3)
        node_2.stop()
        node_2.rejoin_as_standby(node_3)

        # split brain
        node_3.wait_for_catchup(node_1)
        node_1.promote()

        # after rewind only node_1's inserts are visible
        node_1.safe_sql("INSERT INTO public.foo (t) VALUES ('keep this')")
        # bar is unmodified on node_1, replay won't overwrite it
        node_3.safe_sql("INSERT INTO public.bar (t) VALUES ('rewind this')")
        # bump the XID counter so missed rewinds show up as visible rows
        node_1.safe_sql("INSERT INTO public.foo (t) VALUES ('and this')")
        node_1.safe_sql("INSERT INTO public.foo (t) VALUES ('and this too')")

        node_2.poll_until("SELECT COUNT(*) > 1 FROM public.bar", "t")

        # no shutdown checkpoint covering the WAL beyond the last one
        node_2.stop(mode="fast")
        node_3.stop(mode="fast")

        with node_2.db.preserve_config() as conf:
            st.command_ok(
                node_2.tool(
                    "pg_tde_rewind",
                    f"--source-server=host=localhost port={node_1.port} dbname=postgres",
                    f"--target-pgdata={node_2.datadir}",
                    "--debug",
                    f"--config-file={conf}",
                ),
                "run pg_rewind",
            )

        node_2.start()
        assert node_2.safe_sql("SELECT * FROM public.foo") == [["keep this"], ["and this"], ["and this too"]]
        assert node_2.safe_sql("SELECT * FROM public.bar") == [["in both"]]
