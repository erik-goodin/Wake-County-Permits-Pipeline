import json, sqlite3, sys
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent
DB = WORK / "Data" / "Clean" / "permits.db"
src = Path(sys.argv[1]) if len(sys.argv) > 1 else max((WORK / "Data" / "Raw").glob("acs_*.json"))

d = json.loads(src.read_text(encoding="utf-8"))
h, raw = d["header"], d["rows"]
ix = {c: h.index(c) for c in ["NAME", "B01003_001E", "B01003_001M", "B19013_001E", "B19013_001M",
                              "state", "county", "tract"]}

def val(v):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        sys.exit(f"Non-numeric value in {src.name}: {v!r}. Nothing changed.")
    return None if x < 0 else x

rows = []
for r in raw:
    tid = r[ix["state"]] + r[ix["county"]] + r[ix["tract"]]
    pop, pop_m = val(r[ix["B01003_001E"]]), val(r[ix["B01003_001M"]])
    inc, inc_m = val(r[ix["B19013_001E"]]), val(r[ix["B19013_001M"]])
    rows.append((tid, r[ix["NAME"]], pop, pop_m, inc, inc_m, src.name, d.get("pull_date")))
if len({r[0] for r in rows}) != len(rows):
    sys.exit("Duplicate tract IDs in the file. Nothing changed.")

con = sqlite3.connect(DB)
with con:
    con.execute("CREATE TABLE IF NOT EXISTS tract_acs (tract_id TEXT PRIMARY KEY, tract_name TEXT, "
                "population REAL, population_moe REAL, median_income REAL, median_income_moe REAL, "
                "source_file TEXT, pull_date TEXT)")
    con.execute("DELETE FROM tract_acs")
    con.executemany("INSERT INTO tract_acs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

print(f"source: {src.name}, tracts loaded: {len(rows)}")
for c in ["population", "population_moe", "median_income", "median_income_moe"]:
    n = con.execute(f"SELECT COUNT(*) FROM tract_acs WHERE {c} IS NULL").fetchone()[0]
    print(f"{c}: blank in {n} tracts")
has_pt = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'point_tract'").fetchone()
if has_pt:
    miss = con.execute("SELECT COUNT(DISTINCT tract_id) FROM point_tract WHERE tract_id IS NOT NULL "
                       "AND tract_id NOT IN (SELECT tract_id FROM tract_acs)").fetchone()[0]
    none = con.execute("SELECT COUNT(*) FROM tract_acs WHERE tract_id NOT IN "
                       "(SELECT tract_id FROM point_tract WHERE tract_id IS NOT NULL)").fetchone()[0]
    print(f"tract IDs in point_tract but not in tract_acs: {miss}")
    print(f"tracts in tract_acs with no permit points: {none}")
con.close()
