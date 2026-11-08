import csv, os, sqlite3, sys
from pathlib import Path

DB = Path(os.environ.get("PERMITS_DB", Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db"))
OUT = DB.parent / "model"
TABLES = ["fact_permit", "dim_permit_type", "dim_work_class", "dim_permit_status", "dim_district",
          "dim_proposed_use", "dim_tract", "dim_date"]

con = sqlite3.connect(DB)
have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
missing = [t for t in TABLES if t not in have]
if missing:
    sys.exit(f"Table {missing[0]} is missing. Run build_model.py first. Nothing changed.")

OUT.mkdir(exist_ok=True)
tmp, bad = {}, []
for t in TABLES:
    cur = con.execute(f"SELECT * FROM {t}")
    path = OUT / f"{t}.csv.tmp"
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in cur.description])
        for row in cur:
            w.writerow(row)
            n += 1
    total = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t}: {n} rows written, {total} rows in table")
    tmp[t] = path
    if n != total:
        bad.append(t)
con.close()

if bad:
    for p in tmp.values():
        os.remove(p)
    sys.exit(f"Row count differs for {bad[0]}. No files replaced.")
for t, p in tmp.items():
    os.replace(p, OUT / f"{t}.csv")
print(f"model CSV files written: {len(TABLES)}, counts match: True")
