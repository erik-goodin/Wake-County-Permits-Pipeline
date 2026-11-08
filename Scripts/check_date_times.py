import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db")
H = 3600000
con = sqlite3.connect(DB)
cur = con.execute("SELECT * FROM permits")
cols = [c[0] for c in cur.description]
keep = [c for c in cols if c != "row_hash" and not c.startswith("MAILING_")]
idx = [cols.index(c) for c in keep]
rows = {tuple(r[i] for i in idx) for r in cur}
print(f"basis: {len(rows)} distinct rows without the mailing fields")

def hms(t):
    return f"{t // H:02d}:{t // 60000 % 60:02d}:{t // 1000 % 60:02d}.{t % 1000:03d}"

for c in keep:
    if not c.upper().endswith("_DATE"):
        continue
    i = keep.index(c)
    vals = [r[i] for r in rows if isinstance(r[i], (int, float)) and not isinstance(r[i], bool)]
    tod = Counter(int(v) % (24 * H) for v in vals)
    utc0, e4, e5 = tod[0], tod[4 * H], tod[5 * H]
    print(f"{c}: {len(vals)} values | 00:00 UTC {utc0} | 04:00 UTC {e4} | 05:00 UTC {e5} | other {len(vals) - utc0 - e4 - e5}")
    print("  most common UTC times: " + ", ".join(f"{hms(t)} x{n}" for t, n in tod.most_common(3)))
con.close()
