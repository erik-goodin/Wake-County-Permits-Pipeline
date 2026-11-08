import json, os, sys, time, requests
from datetime import date
from pathlib import Path

BASE = "https://api.census.gov/data/2024/acs/acs5"
VARS = ["NAME", "B01003_001E", "B01003_001M", "B19013_001E", "B19013_001M"]
GEO = {"for": "tract:*", "in": "state:37 county:183"}
WORK = Path(__file__).resolve().parent.parent
OUT = WORK / "Data" / "Raw"
RETRIES, WAIT = 3, 2

key = os.environ.get("CENSUS_API_KEY", "").strip()
if not key:
    kf = WORK / "_working" / "census_key.txt"
    key = kf.read_text(encoding="utf-8").strip() if kf.exists() else ""
if not key:
    sys.exit("No Census key. Set CENSUS_API_KEY or fill _working/census_key.txt.")

OUT.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
path = OUT / f"acs_{today}.json"
if path.exists():
    sys.exit(f"{path} already exists. Not overwriting.")

params = {"get": ",".join(VARS), **GEO, "key": key}
for attempt in range(RETRIES + 1):
    try:
        r = requests.get(BASE, params=params, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        err = type(e).__name__
    else:
        if r.status_code < 500:
            break
        err = f"HTTP {r.status_code}"
    if attempt == RETRIES:
        sys.exit(f"Failed after {RETRIES} retries: {err}")
    wait = WAIT * 2 ** attempt
    print(f"Request failed ({err}). Retrying in {wait}s.")
    time.sleep(wait)

if r.status_code != 200:
    sys.exit(f"HTTP {r.status_code}: {r.text.strip()[:200]}")
try:
    data = r.json()
except ValueError:
    sys.exit(f"Response was not JSON: {r.text.strip()[:200]}")

header, rows = data[0], data[1:]
need = VARS + ["state", "county", "tract"]
if sorted(header) != sorted(need):
    sys.exit(f"Unexpected columns: {header}")
if not rows:
    sys.exit("No rows returned. Nothing saved.")

with open(path, "x", encoding="utf-8") as f:
    json.dump({"pull_date": today, "source": BASE, "get": VARS, "geo": GEO,
               "header": header, "rows": rows}, f)

i = {c: header.index(c) for c in header}
def bad(c):
    return sum(1 for x in rows if x[i[c]] is None or float(x[i[c]]) < 0)
ids = {x[i["state"]] + x[i["county"]] + x[i["tract"]] for x in rows}
print(f"saved {len(rows)} tracts, distinct 11-digit IDs: {len(ids)}, all length 11: {all(len(t) == 11 for t in ids)}")
for c in VARS[1:]:
    print(f"{c}: null or negative (suppressed) in {bad(c)} tracts")
print(path)
