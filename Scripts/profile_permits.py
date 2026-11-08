import sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db")
con = sqlite3.connect(DB)
cur = con.execute("SELECT * FROM permits")
cols = [c[0] for c in cur.description]
mail = [c for c in cols if c.startswith("MAILING_")]
keep = [c for c in cols if c != "row_hash" and c not in mail]
for need in ("OBJECTID", "PERMIT_NUMBER"):
    if need not in keep:
        sys.exit(f"Missing column {need}.")
idx = [cols.index(c) for c in keep]
pn_i, oid_i = keep.index("PERMIT_NUMBER"), keep.index("OBJECTID")

def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())

rows = [tuple(r[i] for i in idx) for r in cur]
distinct = set(rows)
print(f"mailing fields set aside: {mail}")
print(f"rows: {len(rows)}, distinct rows without the mailing fields: {len(distinct)}")
print(f"rows with a blank PERMIT_NUMBER: {sum(1 for r in rows if blank(r[pn_i]))}")

by_oid = Counter(r[oid_i] for r in distinct)
print(f"OBJECTIDs with more than one distinct row: {sum(1 for n in by_oid.values() if n > 1)}")

by_pn = defaultdict(set)
for r in distinct:
    if not blank(r[pn_i]):
        by_pn[r[pn_i]].add(r)
multi = {k: v for k, v in by_pn.items() if len(v) > 1}
print(f"PERMIT_NUMBERs: {len(by_pn)}, with more than one distinct row: {len(multi)}")

n_rows = Counter(len(v) for v in multi.values())
for k in sorted(n_rows):
    print(f"  with {k} distinct rows: {n_rows[k]}")
n_oid = Counter(min(len({r[oid_i] for r in v}), 3) for v in multi.values())
print(f"  by number of different OBJECTIDs: 1: {n_oid[1]}, 2: {n_oid[2]}, 3 or more: {n_oid[3]}")

diff = Counter()
for v in multi.values():
    for i, c in enumerate(keep):
        if len({r[i] for r in v}) > 1:
            diff[c] += 1
for c, n in diff.most_common():
    print(f"  field differs within {n} of those PERMIT_NUMBERs: {c}")
con.close()
