import json, sys
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    sys.exit("geopandas is not installed. Run: pip install geopandas")

WORK = Path(__file__).resolve().parent.parent
ZIP = WORK / "Data" / "Raw" / "tiger" / "tl_2020_37_tract.zip"
acs_path = max((WORK / "Data" / "Raw").glob("acs_*.json"))

g = gpd.read_file(ZIP)
print(f"tract file: {ZIP.name}, {len(g)} tracts, CRS: {g.crs}")
need = {"STATEFP", "COUNTYFP", "TRACTCE", "GEOID"}
if not need <= set(g.columns):
    sys.exit(f"Missing columns: {sorted(need - set(g.columns))}. Found: {list(g.columns)}")

wake = g[g["COUNTYFP"] == "183"]
print(f"Wake County (183) tracts: {len(wake)}")
print(f"GEOID length 11 in all Wake tracts: {bool((wake['GEOID'].str.len() == 11).all())}")
print(f"empty geometries: {int(wake.geometry.is_empty.sum())}, invalid geometries: {int((~wake.geometry.is_valid).sum())}")
b = wake.total_bounds
print(f"Wake bounds (lon/lat order): x {b[0]:.4f} to {b[2]:.4f}, y {b[1]:.4f} to {b[3]:.4f}")

d = json.loads(acs_path.read_text(encoding="utf-8"))
h = d["header"]
ids = {r[h.index("state")] + r[h.index("county")] + r[h.index("tract")] for r in d["rows"]}
shp = set(wake["GEOID"])
print(f"ACS file: {acs_path.name}, {len(ids)} tracts")
print(f"in both: {len(ids & shp)}, in ACS only: {len(ids - shp)}, in tract file only: {len(shp - ids)}")
