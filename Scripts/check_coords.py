import json, sys
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "Data" / "Raw"
path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(RAW.glob("raw_*.json"))
d = json.loads(path.read_text(encoding="utf-8"))
rows = [f["attributes"] for p in d["pages"] for f in p["features"]]

def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

pairs = [(num(a.get("X")), num(a.get("Y"))) for a in rows]
ok = [(x, y) for x, y in pairs if x is not None and y is not None and x != 0 and y != 0]
lonlat = sum(1 for x, y in ok if abs(x) <= 180 and abs(y) <= 90)

print(f"rows: {len(rows)}")
print(f"no usable point (X or Y missing, non-numeric, or 0): {len(rows) - len(ok)}")
print(f"usable points: {len(ok)}, look like lon/lat: {lonlat}, look projected (large numbers): {len(ok) - lonlat}")
if ok:
    print(f"X range: {min(x for x, _ in ok):.2f} to {max(x for x, _ in ok):.2f}")
    print(f"Y range: {min(y for _, y in ok):.2f} to {max(y for _, y in ok):.2f}")
    print(f"distinct points: {len(set(ok))}")
