import sqlite3, sys
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    sys.exit("geopandas is not installed. Run: pip install geopandas")

WORK = Path(__file__).resolve().parent.parent
DB = WORK / "Data" / "Clean" / "permits.db"
ZIP = WORK / "Data" / "Raw" / "tiger" / "tl_2020_37_tract.zip"
USABLE = ("typeof(X) IN ('integer','real') AND typeof(Y) IN ('integer','real') "
          "AND X <> 0 AND Y <> 0")

con = sqlite3.connect(DB)
cols = {r[1] for r in con.execute("PRAGMA table_info(permits)")}
if not {"X", "Y"} <= cols:
    sys.exit(f"permits needs X and Y columns. Found: {sorted(cols)}")
con.execute("CREATE TABLE IF NOT EXISTS point_tract "
            "(x REAL, y REAL, tract_id TEXT, PRIMARY KEY (x, y))")

new = con.execute(f"SELECT DISTINCT X, Y FROM permits WHERE {USABLE} "
                  "AND NOT EXISTS (SELECT 1 FROM point_tract t WHERE t.x = permits.X AND t.y = permits.Y)"
                  ).fetchall()
print(f"new points to place: {len(new)}")

if new:
    tracts = gpd.read_file(ZIP)
    tracts = tracts[tracts["COUNTYFP"] == "183"][["GEOID", "geometry"]]
    pts = gpd.GeoDataFrame({"x": [p[0] for p in new], "y": [p[1] for p in new]},
                           geometry=gpd.points_from_xy([p[0] for p in new], [p[1] for p in new]),
                           crs=tracts.crs)
    hit = gpd.sjoin(pts, tracts, how="left", predicate="within")
    dups = int(hit.index.duplicated().sum())
    hit = hit[~hit.index.duplicated(keep="first")]
    rows = [(float(r.x), float(r.y), None if r.GEOID != r.GEOID else r.GEOID) for r in hit.itertuples()]
    with con:
        con.executemany("INSERT INTO point_tract VALUES (?, ?, ?)", rows)
    m = sum(1 for r in rows if r[2] is not None)
    print(f"matched: {m}, unmatched (inside no Wake tract, or exactly on a boundary): {len(rows) - m}")
    print(f"points in more than one tract: {dups}")

tot, tm = con.execute("SELECT COUNT(*), COUNT(tract_id) FROM point_tract").fetchone()
print(f"point_tract now: {tot} points, {tm} with a tract")
R = con.execute("SELECT COUNT(*) FROM permits").fetchone()[0]
usable = con.execute(f"SELECT COUNT(*) FROM permits WHERE {USABLE}").fetchone()[0]
with_t = con.execute("SELECT COUNT(*) FROM permits p JOIN point_tract t ON p.X = t.x AND p.Y = t.y "
                     "WHERE t.tract_id IS NOT NULL").fetchone()[0]
print(f"permit rows: {R}, no usable point: {R - usable}, with a tract: {with_t}, usable point but no tract: {usable - with_t}")
con.close()
