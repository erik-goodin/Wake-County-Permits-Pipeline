import hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "Data" / "Raw"
if len(sys.argv) == 3:
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
else:
    old, new = sorted(RAW.glob("raw_*.json"))[-2:]

def load(p):
    d = json.loads(p.read_text(encoding="utf-8"))
    return [f["attributes"] for pg in d["pages"] for f in pg["features"]]

def fp(a):
    return hashlib.sha256(json.dumps(a, sort_keys=True).encode("utf-8")).hexdigest()

def summarize(p):
    rows = load(p)
    oids = [a.get("OBJECTID") for a in rows if isinstance(a.get("OBJECTID"), (int, float))]
    return Counter(fp(a) for a in rows), len(rows), {k for a in rows for k in a}, max(oids)

def pick(p, want):
    out = {}
    for a in load(p):
        h = fp(a)
        if h in want and h not in out:
            out[h] = a
    return out

c_old, n_old, f_old, max_old = summarize(old)
c_new, n_new, f_new, _ = summarize(new)
removed, added = c_old - c_new, c_new - c_old
r_rep, a_rep = pick(old, set(removed)), pick(new, set(added))

def group(counter, rep):
    g = defaultdict(list)
    for h, n in counter.items():
        g[rep[h].get("OBJECTID")].extend([rep[h]] * n)
    return g

rem, add = group(removed, r_rep), group(added, a_rep)
both = set(rem) & set(add)
only_r, only_a = set(rem) - both, set(add) - both

print(f"old: {old.name}, {n_old} rows")
print(f"new: {new.name}, {n_new} rows")
print(f"same field set: {f_old == f_new}" + ("" if f_old == f_new else f" (old only {sorted(f_old - f_new)}, new only {sorted(f_new - f_old)})"))
print(f"rows only in old (removed): {sum(removed.values())}, rows only in new (added): {sum(added.values())}")
print(f"OBJECTIDs on both sides (changed): {len(both)}, rows removed {sum(len(rem[i]) for i in both)}, rows added {sum(len(add[i]) for i in both)}")
one = [i for i in both if len(rem[i]) == 1 and len(add[i]) == 1]
print(f"  one row each side: {len(one)}, more than one row on a side: {len(both) - len(one)}")
diff = Counter()
for i in one:
    o, n = rem[i][0], add[i][0]
    for k in set(o) | set(n):
        if o.get(k) != n.get(k):
            diff[k] += 1
for k, v in diff.most_common():
    print(f"  field differs in {v} of those: {k}")
print(f"OBJECTIDs only removed: {len(only_r)} ({sum(len(rem[i]) for i in only_r)} rows)")
print(f"OBJECTIDs only added: {len(only_a)} ({sum(len(add[i]) for i in only_a)} rows), above old max OBJECTID: {sum(1 for i in only_a if i > max_old)}")
pr = {a.get("PERMIT_NUMBER") for i in only_r for a in rem[i]}
pa = {a.get("PERMIT_NUMBER") for i in only_a for a in add[i]}
print(f"PERMIT_NUMBERs in both the only-removed and only-added groups: {len(pr & pa)}")
