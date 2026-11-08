import subprocess, sys
from datetime import datetime
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent
SCRIPTS = WORK / "Scripts"
LOG = WORK / "_working" / "refresh_log.txt"

def run(script):
    return subprocess.run([sys.executable, str(SCRIPTS / script)], cwd=WORK, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")

def pick(r, start):
    return next((l for l in r.stdout.splitlines() if l.startswith(start)), "no result line")

def last(r):
    lines = (r.stderr or r.stdout).strip().splitlines()
    return lines[-1] if lines else "no message"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")

fetch = run("fetch_permits.py")
if fetch.returncode != 0:
    log(f"FAILED at fetch | {last(fetch)}")
    sys.exit(1)

load = run("load_permits.py")
if load.returncode != 0:
    log(f"FAILED at load | {last(load)}")
    sys.exit(1)

tracts = run("build_point_tract.py")
if tracts.returncode != 0:
    log(f"FAILED at tracts | {last(tracts)}")
    sys.exit(1)

clean = run("build_clean.py")
if clean.returncode != 0:
    log(f"FAILED at clean | {last(clean)}")
    sys.exit(1)

model = run("build_model.py")
if model.returncode != 0:
    log(f"FAILED at model | {last(model)}")
    sys.exit(1)

export = run("export_model_csv.py")
if export.returncode != 0:
    log(f"FAILED at export | {last(export)}")
    sys.exit(1)

log(f"OK | fetch: {pick(fetch, 'expected')} | load: {pick(load, 'added')} | tracts: {pick(tracts, 'permit rows')} | clean: {pick(clean, 'permits_clean rows')} | model: {pick(model, 'fact_permit rows')} | export: {pick(export, 'model CSV files')}")
