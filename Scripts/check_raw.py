import json, sys
from collections import Counter
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "Data" / "Raw"
path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(RAW.glob("raw_*.json"))

d = json.loads(path.read_text(encoding="utf-8"))
sizes = [len(p["features"]) for p in d["pages"]]
ids = [f["attributes"]["OBJECTID"] for p in d["pages"] for f in p["features"]]
dupes = sum(c - 1 for c in Counter(ids).values() if c > 1)

print(f"file: {path.name}, {path.stat().st_size / 1e6:.1f} MB")
print(f"pages: {len(sizes)}, first {sizes[0]}, last {sizes[-1]}")
print(f"rows: {len(ids)}, expected: {d['expected_count']}, match: {len(ids) == d['expected_count']}")
print(f"extra rows from repeated OBJECTIDs: {dupes}")
