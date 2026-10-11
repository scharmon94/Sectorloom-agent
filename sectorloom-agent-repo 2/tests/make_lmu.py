"""Builds a plausible LMU-shaped DuckDB file to exercise the reader."""
import math, sys, duckdb, os

def build(path, style='metres_kmh'):
    if os.path.exists(path): os.remove(path)
    con = duckdb.connect(path)
    con.execute("CREATE TABLE session_info (key VARCHAR, value VARCHAR)")
    con.execute("INSERT INTO session_info VALUES ('Track','Circuit de la Sarthe'),"
                "('Car','Porsche 963'),('Driver','Test Driver')")
    cols = ("Time DOUBLE, LapNumber INTEGER, LapDistance DOUBLE, Speed DOUBLE, "
            "Throttle DOUBLE, Brake DOUBLE, SteeringAngle DOUBLE, Gear INTEGER, "
            "EngineRPM DOUBLE, PositionX DOUBLE, PositionY DOUBLE, FuelRemaining DOUBLE")
    con.execute(f"CREATE TABLE channels ({cols})")
    rows, t, hz, LEN, fuel = [], 0.0, 50.0, 4200.0, 90.0
    for lap in range(7):
        wob = 1.0 + 0.01 * math.sin(lap * 2.3)
        nlap = int(hz * 96 * wob)
        for i in range(nlap):
            p = i / nlap
            corner = math.sin(p * 2 * math.pi * 4)
            kmh = max(60.0, (210 + 60 * corner) * wob)
            acc = 20 * math.cos(p * 2 * math.pi * 4)
            thr = max(0.0, min(100.0, 60 + acc * 2))
            brk = max(0.0, min(100.0, -acc * 3))
            if thr > 5: brk = 0.0
            ang = p * 2 * math.pi
            r = 900 + 200 * math.sin(4 * ang)
            fuel -= thr * 0.00004
            rows.append((t, lap, p * LEN, kmh, thr, brk, math.atan(corner) * 3,
                         max(1, min(8, int(kmh / 30) + 1)), 5000 + kmh * 20,
                         r * math.cos(ang), 0.6 * r * math.sin(ang), max(0.0, fuel)))
            t += 1.0 / hz
    con.executemany("INSERT INTO channels VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    print(f"wrote {path}: {len(rows)} samples across 7 laps")

def build_unknown(path):
    if os.path.exists(path): os.remove(path)
    con = duckdb.connect(path)
    con.execute("CREATE TABLE blobs (a VARCHAR, b BLOB)")
    con.execute("INSERT INTO blobs VALUES ('x', NULL)")
    con.close()
    print(f"wrote {path}: deliberately unrecognisable")

if __name__ == '__main__':
    # The second file — the deliberately unreadable one, for exercising
    # the schema prober — used to be written to a hard-coded scratch
    # path that exists on one Linux box and nowhere else. On Windows
    # that directory is absent, duckdb raises, and this script exits
    # non-zero, which takes the whole end-to-end suite down with it.
    # It now lands beside the real file, and only when asked for.
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    out = args[0] if args else 'lmu.duckdb'
    build(out)
    if '--with-unknown' in sys.argv:
        beside = os.path.dirname(os.path.abspath(out)) or '.'
        build_unknown(os.path.join(beside, 'unknown.duckdb'))
