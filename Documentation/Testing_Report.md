# Testing Report

Results and method of the debug-and-test pass on the Wake County permits pipeline (Nov 2026).

## Summary

| | |
|---|---|
| Tests | 52, all passing (`python -m pytest Tests -q`, about 50 s) |
| Bugs found and fixed | 2 |
| Hardening added | 3 changes (contact-detail redaction, shrink guard, Census key handling) |
| Mutation testing | 5 scripts; every mutant killed except 2 (1 equivalent, 1 unreachable) |
| Not tested | `fetch_acs`, `load_acs`, `build_point_tract`, `refresh`, `check_*` / `profile_*` helpers |

## Approach

1. **Debug.** Read and ran the pipeline scripts, then looked for faults by reading the code against what each step is meant to guarantee.
2. **Test first.** For each fault, write a test that defines the correct behavior, confirm it fails on the bug, then fix the script with a minimal change.
3. **Property tests.** One Hypothesis test checks `build_clean` invariants on generated inputs.
4. **Mutation testing.** For each surviving mutant, add or strengthen a test until it is killed.
5. **Real data.** After the fixes, run the cleaning and model steps on the real database and check the integrity lines they print.

### How the tests run

The scripts execute at import time and have no functions to import, so the tests run each script as a **subprocess against a temporary database**. Small environment-variable overrides were added so the tests never touch real data (defaults unchanged):

| Variable | Purpose |
|---|---|
| `PERMITS_DB` | SQLite database path |
| `PERMITS_WORK` | project root (`load_permits.py`) |
| `PERMITS_RAW` | raw-pull folder (`load_permits.py`) |
| `PERMITS_URL`, `PERMITS_PAGE`, `PERMITS_WAIT` | endpoint, page size, retry wait for `fetch_permits.py` |
| `PERMITS_ALLOW_SHRINK=1` | allow `load_permits.py` to load a pull more than 5% smaller than the table |

`fetch_permits.py` is tested against a **local fake ArcGIS server** with scripted failures, so no test touches the network.

## Bugs found and fixed

| # | Script | Problem | Evidence | Fix |
|---|---|---|---|---|
| 1 | `load_permits.py` | Picked the newest `raw_*.json`, including `*.INCOMPLETE.json`. A truncated pull would delete rows from the table. | Test loaded 1 row instead of 2 when an INCOMPLETE file was newer. | Skip files with `INCOMPLETE` in the name. |
| 2 | `build_clean.py` | Aborted with "Date out of range" on any date before 1970 on Windows, because `fromtimestamp` rejects negative values. | Test with `ISSUE_DATE = -86400000` failed. | Compute dates as epoch plus `timedelta`. |

One failing test was a mistake in the test, not the code: SQLite stores `True` as `1`, so a boolean coordinate can never reach `build_clean`. The case was removed.

## Hardening added

| Change | Where | Why |
|---|---|---|
| Redact phone numbers and email addresses in `DESCRIPTION` (`[phone removed]`, `[email removed]`) | `build_clean.py` | A scan found about 100 distinct phone numbers and 75 emails, including personal addresses, in free-text descriptions. Redacted 213 descriptions on the real data. No SSN patterns found. |
| Abort if a pull would shrink the table by more than 5% | `load_permits.py` | A bad but count-consistent pull would otherwise delete rows. The override is `PERMITS_ALLOW_SHRINK=1`. |
| Census key from `CENSUS_API_KEY`, falling back to `_working/census_key.txt` | `fetch_acs.py` | Avoids keeping the key in a file. Parse-checked only; not run. |

## Test inventory

| File | Tests | Covers |
|---|---|---|
| `Tests/test_pipeline.py` | 25 | `load_permits` and `build_clean` (details below) |
| `Tests/test_model.py` | 9 | `build_model` |
| `Tests/test_fetch.py` | 14 | `fetch_permits` |
| `Tests/test_export.py` | 4 | `export_model_csv` |

**`load_permits.py`**
- Skips INCOMPLETE files.
- Adds new rows, removes vanished ones, and is idempotent on reload.
- Keeps exact duplicate rows and counts multiple copies correctly.
- Rejects a field-set change with a message naming the fields.
- Prints exact added, removed and total counts.
- Shrink guard: aborts at more than 5%, allows exactly 5% and growth, aborts on an empty source, and honors the override.

**`build_clean.py`**
- Drops `row_hash`, `CONTRACTOR` and `MAILING_*`.
- Trims `DESCRIPTION`, fills blank or null `PROPOSED_USE` with "Not recorded", and redacts phone numbers and emails.
- Date conversion: epoch ms to ISO, including pre-1970 and day-boundary values. A non-numeric or out-of-range date aborts with a message.
- `has_point`: zero, null, string and negative coordinates.
- Collapses rows identical except `OBJECTID`, flags permit numbers that still repeat, and leaves blank permit numbers alone.
- A duplicate `OBJECTID` or a missing required column aborts without creating `permits_clean`.
- Column types written to SQLite (`TEXT`, `REAL`, `INTEGER`).
- Every line of the printed summary.
- Hypothesis property test, 25 examples per run:
  - descriptions are trimmed
  - dates are 10-character strings
  - the number of distinct permit numbers never grows
  - a rebuild gives the same row count

**`build_model.py`**
- Aborts on a missing table or column, or when no dates exist.
- `dim_date` spans the minimum to maximum across all four date columns with correct month and quarter values.
- Null categories become "Unknown" with no null keys in the fact table.
- Tract join applies only to rows with a point.
- Unknown tract IDs are reported, totals match the source, and a rebuild is idempotent.

**`fetch_permits.py`** (fake server)
- Multi-page pulls, a server page cap below the requested size, and an exact multiple of the page size.
- A count mismatch in either direction, or a missing transfer-limit flag, is saved as `.INCOMPLETE.json` with a failing exit code.
- A zero count saves nothing. An existing file is never overwritten.
- Retries on 503, 429 and invalid JSON with doubling waits, giving up after 3 retries.
- 404 and API error bodies are not retried. Connection errors are retried and then fail.
- No `.tmp` files are left behind.

**`export_model_csv.py`**
- All 8 CSVs written with the right headers and rows.
- Commas, quotes, newlines and NULLs round-trip.
- A missing table aborts with no output folder.
- Rerunning overwrites old files, and an empty table exports header-only.

## Mutation testing

`Tests/mutate.py` is a small AST mutator, written because the scripts have no importable functions (mutmut and cosmic-ray need modules). It changes comparisons, arithmetic operators, `and`/`or`, and the constants 0, 1 and 1000, runs the suite once per mutant, and lists survivors.

| Script | Mutants | Killed | Survived |
|---|---|---|---|
| `build_clean.py` | 67 | 67 | 0 |
| `load_permits.py` | 31 | 31 | 0 |
| `build_model.py` | 27 | 27 | 0 |
| `export_model_csv.py` | 12 | 11 | 1 |
| `fetch_permits.py` | 20 | 19 | 1 |

Run it with: `python Tests/mutate.py build_clean.py load_permits.py build_model.py export_model_csv.py fetch_permits.py`

The first run on `build_clean.py` and `load_permits.py` killed 57 of 87 mutants. The 30 survivors were mostly the printed counters, the SQLite column typing, and a few untested branches. New tests were added for each, and the rerun killed all 87.

**The two survivors**
- `export_model_csv.py`, the `bad[0]` in the "Row count differs" message. It runs only if a table's row count changes during the export, which can't be triggered from outside the script. That error path is untested.
- `fetch_permits.py`, `range(RETRIES + 1)` changed to `RETRIES + 2`. This is an equivalent mutant: the loop exits at `attempt == RETRIES` before the extra iteration.

**Limits of the mutator.** It only applies the operator and constant swaps above. The final per-script runs skip the Hypothesis test, and the 67-mutant `build_clean.py` run used the suite as of that date. The other scripts were not re-run after the last edit to their tests; the table shows the last run for each.

## Real-data verification

`build_clean.py`, `build_model.py` and `export_model_csv.py` were run on the real database (Nov 4 pull and later). Results from the first run, on 198,057 source rows:

| Check | Result |
|---|---|
| Rows kept after collapsing | 196,622 (384 collapsed) |
| `fact_permit` rows vs `permits_clean` | equal |
| Fact rows missing a category key | 0 |
| Tract IDs in the fact table but not in `dim_tract` | 0 |
| Fact dates outside `dim_date` | 0 |
| Valuation, square-feet and fee totals vs `permits_clean` | match |
| Rows with a point but no tract | 12 |

After the redaction change, a rebuild on the later pull gave 196,663 rows with 213 descriptions redacted, and a scan of `fact_permit.csv` found no phone numbers or emails.

The 12 points with no tract are the boundary-or-outside-Wake case the script already reports. They were not investigated further.

## Not tested or not verified

- **No tests:** `fetch_acs.py`, `load_acs.py`, `build_point_tract.py` (needs geopandas and the TIGER file), `refresh.py`, and the `check_*` / `profile_*` / `compare_pulls` helpers.
- **Never run against the live API:** `fetch_permits.py` was tested only against the fake server. `fetch_acs.py` was only parse-checked after the key change.
- **Redaction is pattern-based.** It catches phone numbers and email addresses only. Names or street addresses typed into descriptions would not be caught.
- **Raw layer unredacted.** The `permits` table and `Data/Raw/*.json` still contain mailing addresses, contractors and original descriptions.
- **Dashboard.** The Power BI files were not examined or tested.
- **Platform.** All tests were run on Windows with Python 3.14.
