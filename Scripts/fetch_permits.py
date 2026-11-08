import json, os, sys, time, requests
from datetime import date
from pathlib import Path

URL = os.environ.get("PERMITS_URL", "https://maps.wake.gov/arcgis/rest/services/Inspections/Building_Permits/MapServer/0/query")
PAGE = int(os.environ.get("PERMITS_PAGE", 2000))
RETRIES, WAIT = 3, float(os.environ.get("PERMITS_WAIT", 2))
RETRY_STATUS = {429, 500, 502, 503, 504}
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "Data" / "Raw"

def get(params):
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(URL, params={**params, "f": "json"}, timeout=60)
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            err = type(e).__name__
        else:
            if r.status_code in RETRY_STATUS or r.status_code >= 500:
                err = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()      # other 4xx: not retryable
                try:
                    data = r.json()
                except ValueError:        # e.g. HTML error page with 200
                    err = "InvalidJSON"
                else:
                    if "error" in data:
                        sys.exit(f"API error: {data['error']}")
                    return data
        if attempt == RETRIES:
            sys.exit(f"Failed after {RETRIES} retries: {err}")
        wait = WAIT * 2 ** attempt
        print(f"Request failed ({err}). Retrying in {wait}s.")
        time.sleep(wait)

OUT.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
path = OUT / f"raw_{today}.json"
if path.exists():
    sys.exit(f"{path} already exists. Not overwriting.")

expected = get({"where": "1=1", "returnCountOnly": "true"})["count"]
if expected == 0:
    sys.exit("Count is 0. Nothing saved.")

pages, offset = [], 0
while True:
    page = get({"where": "1=1", "outFields": "*", "returnGeometry": "false",
                "orderByFields": "OBJECTID", "resultOffset": offset,
                "resultRecordCount": PAGE})
    n = len(page["features"])
    if n == 0:
        break
    pages.append(page)
    offset += n
    # Server may cap a page below PAGE; only this flag says whether more remain.
    if not page.get("exceededTransferLimit"):
        break

match = expected == offset
# Write to a temp name, then rename, so an interrupted run never leaves a
# truncated file that looks complete.
final = path if match else OUT / f"raw_{today}.INCOMPLETE.json"
tmp = final.with_name(final.name + ".tmp")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"pull_date": today, "expected_count": expected,
               "saved_count": offset, "pages": pages}, f)
tmp.replace(final)

print(f"expected {expected}, saved {offset}, match: {match}")
print(final)
if not match:
    sys.exit("Count mismatch: saved as INCOMPLETE, not as the final raw file.")
