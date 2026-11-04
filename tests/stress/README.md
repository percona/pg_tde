# pg_tde stress scenarios

Randomized stress scenarios for pg_tde, built on stormweaver. They are not
part of the pytest/meson test suite and have to be run by hand:

    stormweaver tests/stress/basic_tde.py -i /path/to/pg-with-pg_tde --workers 4 [--tde on|on_wal]

Useful options: `--duration` (seconds per cycle), `--workers`, `--repeat`
(number of cycles), `--seed` (0 = random), `--tde`. `--tde on` sets up a
database key only, `--tde on_wal` sets up global keys, a default key and
enables WAL encryption. Logs go to `logs/` in the current directory.
