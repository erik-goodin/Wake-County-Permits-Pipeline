import json, sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "Data" / "Raw"
path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(RAW.glob("raw_*.json"))
d = json.loads(path.read_text(encoding="utf-8"))
rows = [f["attributes"] for p in d["pages"] for f in p["features"]]

by_id = defaultdict(list)
for a in rows:
    by_id[a["OBJECTID"]].append(a)
rep = {k: v for k, v in by_id.items() if len(v) > 1}

field_diff, n_diff = Counter(), Counter()
for v in rep.values():
    keys = set().union(*v)
    diff = [k for k in keys if len({json.dumps(a.get(k)) for a in v}) > 1]
    if diff:
        field_diff.update(diff)
        n_diff[len(diff)] += 1

print(f"repeated OBJECTIDs: {len(rep)}, with differing copies: {sum(n_diff.values())}")
print("fields that differ across copies (number of OBJECTIDs where it differs):")
for k, c in field_diff.most_common():
    print(f"  {k}: {c}")
print(f"number of differing fields per OBJECTID: {dict(sorted(n_diff.items()))}")

pn_ids, pn_rows = defaultdict(set), Counter()
blank = 0
for a in rows:
    k = a.get("PERMIT_NUMBER")
    if k is None or not str(k).strip():
        blank += 1
    else:
        pn_ids[k].add(a["OBJECTID"])
        pn_rows[k] += 1
pn_rep = [k for k, c in pn_rows.items() if c > 1]
print(f"PERMIT_NUMBER: blank {blank}, distinct {len(pn_rows)}, repeating {len(pn_rep)}, max copies {max(pn_rows.values())}")
print(f"  repeating PERMIT_NUMBERs on one OBJECTID: {sum(1 for k in pn_rep if len(pn_ids[k]) == 1)}, across several OBJECTIDs: {sum(1 for k in pn_rep if len(pn_ids[k]) > 1)}")

sigs = Counter(json.dumps(a, sort_keys=True) for a in rows)
print(f"exact duplicate rows (all fields): {sum(c - 1 for c in sigs.values() if c > 1)} extra rows")
