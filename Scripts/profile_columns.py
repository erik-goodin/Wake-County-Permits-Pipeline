import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DB = Path(Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db")
con = sqlite3.connect(DB)
cur = con.execute("SELECT * FROM permits")
cols = [c[0] for c in cur.description]
keep = [c for c in cols if c != "row_hash" and not c.startswith("MAILING_")]
idx = [cols.index(c) for c in keep]
rows = {tuple(r[i] for i in idx) for r in cur}
now_ms = datetime.now(timezone.utc).timestamp() * 1000
print(f"basis: {len(rows)} distinct rows without the mailing fields")

def day(ms):
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return "out of range"

for i, c in enumerate(keep):
    vals = [r[i] for r in rows]
    kinds = Counter(type(v).__name__ for v in vals)
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    strs = [v for v in vals if isinstance(v, str)]
    parts = [f"{c}: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())),
             f"distinct {len(set(vals))}"]
    if strs:
        groups = defaultdict(set)
        for v in strs:
            groups[" ".join(v.lower().split())].add(v)
        parts.append(f"blank text {sum(1 for v in strs if not v.strip())}, "
                     f"edge spaces {sum(1 for v in strs if v != v.strip())}, "
                     f"groups differing only by case/spacing {sum(1 for g in groups.values() if len(g) > 1)}")
    if nums and c.upper().endswith("_DATE"):
        pos = [v for v in nums if v > 0]
        parts.append(f"dates {day(min(pos)) if pos else 'none'} to {day(max(pos)) if pos else 'none'}, "
                     f"zero {sum(1 for v in nums if v == 0)}, negative {sum(1 for v in nums if v < 0)}, "
                     f"after today {sum(1 for v in nums if v > now_ms)}")
    elif nums:
        parts.append(f"range {min(nums)} to {max(nums)}, zero {sum(1 for v in nums if v == 0)}, "
                     f"negative {sum(1 for v in nums if v < 0)}")
    print(" | ".join(parts))
con.close()
