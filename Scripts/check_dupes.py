import json, sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "Data" / "Raw"
path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(RAW.glob("raw_*.json"))
d = json.loads(path.read_text(encoding="utf-8"))

rows = [(pi, f["attributes"]) for pi, p in enumerate(d["pages"]) for f in p["features"]]
ids = [a["OBJECTID"] for _, a in rows]
counts = Counter(ids)
rep = {k for k, c in counts.items() if c > 1}

groups = defaultdict(list)
for pi, a in rows:
    if a["OBJECTID"] in rep:
        groups[a["OBJECTID"]].append((pi, json.dumps(a, sort_keys=True)))

identical = sum(1 for g in groups.values() if len({s for _, s in g}) == 1)
where = Counter()
for g in groups.values():
    gap = max(p for p, _ in g) - min(p for p, _ in g)
    where["same page" if gap == 0 else "adjacent pages" if gap == 1 else "2+ pages apart"] += 1
backsteps = sum(1 for x, y in zip(ids, ids[1:]) if y < x)

print(f"rows: {len(ids)}, distinct OBJECTIDs: {len(counts)}, expected: {d['expected_count']}")
print(f"rows minus distinct: {len(ids) - len(counts)}, expected minus distinct: {d['expected_count'] - len(counts)}")
print(f"OBJECTIDs that repeat: {len(rep)}, max copies of one: {max(counts.values())}")
print(f"  identical in every field: {identical}, differing in some field: {len(rep) - identical}")
print(f"  location of copies: {dict(where)}")
print(f"OBJECTID min {min(ids)}, max {max(ids)}, out-of-order steps: {backsteps}")
