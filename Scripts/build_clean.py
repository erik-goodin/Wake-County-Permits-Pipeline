import os, re, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path(os.environ.get("PERMITS_DB", Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db"))
DROP = {"row_hash", "CONTRACTOR"}

con = sqlite3.connect(DB)
cur = con.execute("SELECT * FROM permits")
cols = [c[0] for c in cur.description]
keep = [c for c in cols if c not in DROP and not c.startswith("MAILING_")]
for need in ("OBJECTID", "PERMIT_NUMBER", "DESCRIPTION", "PROPOSED_USE", "X", "Y"):
    if need not in keep:
        sys.exit(f"Missing column {need}. Nothing changed.")
idx = [cols.index(c) for c in keep]
pos = {c: i for i, c in enumerate(keep)}
read = 0
distinct = set()
for r in cur:
    read += 1
    distinct.add(tuple(r[i] for i in idx))

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-. ])\d{3}[-. ]\d{4}(?!\d)")

def redact(text):
    return PHONE.sub("[phone removed]", EMAIL.sub("[email removed]", text))

def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())

# one row per PERMIT_NUMBER: copies identical except OBJECTID collapse to the lowest OBJECTID
oid = pos["OBJECTID"]
by_pn = defaultdict(list)
solo = []
for r in distinct:
    (solo if blank(r[pos["PERMIT_NUMBER"]]) else by_pn[r[pos["PERMIT_NUMBER"]]]).append(r)
kept, flagged_pns = [], set()
for pn, rs in by_pn.items():
    groups = {}
    for r in rs:
        k = r[:oid] + r[oid + 1:]
        if k not in groups or r[oid] < groups[k][oid]:
            groups[k] = r
    kept.extend((r, len(groups) > 1) for r in groups.values())
    if len(groups) > 1:
        flagged_pns.add(pn)
kept.extend((r, False) for r in solo)
if len({r[oid] for r, _ in kept}) != len(kept):
    sys.exit("OBJECTID is not unique after collapsing. Nothing changed.")

date_cols = [c for c in keep if c.upper().endswith("_DATE")]
n_desc = n_null = n_ws = n_pii = 0
n_date = dict.fromkeys(date_cols, 0)

def to_day(v, c):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        sys.exit(f"Non-numeric value in {c}. Nothing changed.")
    try:
        d = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=v)
    except (OverflowError, OSError, ValueError):
        sys.exit(f"Date out of range in {c}. Nothing changed.")
    n_date[c] += 1
    return d.date().isoformat()

def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

out = []
for r, rep in kept:
    r = list(r)
    d = r[pos["DESCRIPTION"]]
    if isinstance(d, str) and d != d.strip():
        r[pos["DESCRIPTION"]] = d.strip()
        n_desc += 1
    d = r[pos["DESCRIPTION"]]
    if isinstance(d, str) and redact(d) != d:
        r[pos["DESCRIPTION"]] = redact(d)
        n_pii += 1
    p = r[pos["PROPOSED_USE"]]
    if p is None:
        n_null += 1
    elif isinstance(p, str) and not p.strip():
        n_ws += 1
    if blank(p):
        r[pos["PROPOSED_USE"]] = "Not recorded"
    for c in date_cols:
        r[pos[c]] = to_day(r[pos[c]], c)
    x, y = r[pos["X"]], r[pos["Y"]]
    has_pt = 1 if num(x) and num(y) and x != 0 and y != 0 else 0
    out.append(r + [has_pt, 1 if rep else 0])

def sqltype(c):
    if c in date_cols:
        return "TEXT"
    kinds = {type(r[pos[c]]).__name__ for r in out if r[pos[c]] is not None}
    if kinds <= {"int"}:
        return "INTEGER"
    if kinds <= {"int", "float"}:
        return "REAL"
    return "TEXT"

defs = ", ".join(f'"{c}" {sqltype(c)}' + (" PRIMARY KEY" if c == "OBJECTID" else "") for c in keep)
with con:
    con.execute("DROP TABLE IF EXISTS permits_clean")
    con.execute(f"CREATE TABLE permits_clean ({defs}, has_point INTEGER, permit_number_repeats INTEGER)")
    con.executemany(f"INSERT INTO permits_clean VALUES ({', '.join('?' * (len(keep) + 2))})", out)

n = con.execute("SELECT COUNT(*) FROM permits_clean").fetchone()[0]
rep_rows = con.execute("SELECT COUNT(*) FROM permits_clean WHERE permit_number_repeats = 1").fetchone()[0]
hp = dict(con.execute("SELECT has_point, COUNT(*) FROM permits_clean GROUP BY has_point"))
print(f"rows read: {read}, distinct without mailing fields: {len(distinct)}")
print(f"rows kept: {len(out)}, collapsed (identical except OBJECTID): {len(distinct) - len(out)}")
print(f"PERMIT_NUMBERs still on more than one row: {len(flagged_pns)}, flagged rows: {rep_rows}")
print(f"DESCRIPTION trimmed: {n_desc}")
print(f"DESCRIPTION contact details redacted: {n_pii}")
print(f"PROPOSED_USE set to 'Not recorded': {n_null} null, {n_ws} whitespace-only")
print("dates converted: " + ", ".join(f"{c} {k}" for c, k in n_date.items()))
print(f"has_point 1: {hp.get(1, 0)}, 0: {hp.get(0, 0)}")
print(f"permits_clean rows: {n}, matches kept rows: {n == len(out)}")
con.close()
