import hashlib, json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORK = Path(os.environ.get("PERMITS_WORK", Path(__file__).resolve().parent.parent))
DB = Path(os.environ.get("PERMITS_DB", WORK / "Data" / "Clean" / "permits.db"))
RAW = Path(os.environ.get("PERMITS_RAW", WORK / "Data" / "Raw"))
src = Path(sys.argv[1]) if len(sys.argv) > 1 else max(p for p in RAW.glob("raw_*.json") if "INCOMPLETE" not in p.name)

d = json.loads(src.read_text(encoding="utf-8"))
rows = [f["attributes"] for p in d["pages"] for f in p["features"]]
cols = list(dict.fromkeys(k for a in rows for k in a))

def fingerprint(a):
    return hashlib.sha256(json.dumps(a, sort_keys=True).encode("utf-8")).hexdigest()

by_hash = defaultdict(list)
for a in rows:
    by_hash[fingerprint(a)].append(a)

con = sqlite3.connect(DB)
names = ", ".join(f'"{c}"' for c in cols)
con.execute(f"CREATE TABLE IF NOT EXISTS permits (row_hash TEXT NOT NULL, {names})")
con.execute("CREATE INDEX IF NOT EXISTS ix_permits_hash ON permits(row_hash)")
con.execute("CREATE TABLE IF NOT EXISTS load_log (loaded_at TEXT, source_file TEXT, pull_date TEXT, "
            "source_rows INT, added INT, removed INT, rows_after INT)")

existing = [r[1] for r in con.execute("PRAGMA table_info(permits)")][1:]
if set(existing) != set(cols):
    sys.exit(f"Fields differ from the table. In file only: {sorted(set(cols) - set(existing))}. "
             f"In table only: {sorted(set(existing) - set(cols))}. Nothing changed.")

have = dict(con.execute("SELECT row_hash, COUNT(*) FROM permits GROUP BY row_hash"))
before = sum(have.values())
if len(rows) * 100 < before * 95 and os.environ.get("PERMITS_ALLOW_SHRINK") != "1":
    sys.exit(f"{src.name} has {len(rows)} rows, which shrinks the table from {before} to {len(rows)} "
             f"(more than 5%). Set PERMITS_ALLOW_SHRINK=1 to load it anyway. Nothing changed.")
insert = f"INSERT INTO permits (row_hash, {names}) VALUES ({', '.join('?' * (len(cols) + 1))})"
added = removed = 0
with con:
    for h, rs in by_hash.items():
        n = have.get(h, 0)
        if len(rs) > n:
            con.executemany(insert, [(h, *[a.get(c) for c in cols]) for a in rs[n:]])
            added += len(rs) - n
    for h, n in have.items():
        want = len(by_hash.get(h, ()))
        if n > want:
            con.execute("DELETE FROM permits WHERE rowid IN "
                        "(SELECT rowid FROM permits WHERE row_hash = ? LIMIT ?)", (h, n - want))
            removed += n - want
    after = con.execute("SELECT COUNT(*) FROM permits").fetchone()[0]
    con.execute("INSERT INTO load_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), src.name, d.get("pull_date"),
                 len(rows), added, removed, after))

now = dict(con.execute("SELECT row_hash, COUNT(*) FROM permits GROUP BY row_hash"))
same = now == {h: len(rs) for h, rs in by_hash.items()}
print(f"source: {src.name}, {len(rows)} rows")
print(f"added {added}, removed {removed}, rows now {after}, table matches source: {same}")
con.close()
