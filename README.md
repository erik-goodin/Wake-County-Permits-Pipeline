# Wake County Building Permits Pipeline

Pulls building permits from the Wake County ArcGIS API, cleans them, joins them to Census tracts and ACS data, and exports a star schema (SQLite + CSV) for analysis.

## Layout

| Folder | Contents |
|---|---|
| `Scripts/` | Pipeline scripts and one-off `check_*` / `profile_*` / `compare_pulls` helpers |
| `Tests/` | pytest + Hypothesis tests and `mutate.py` (mutation tester) |
| `Data/Raw/` | Dated API pulls (`raw_YYYY-MM-DD.json`), ACS pull (`acs_*.json`), TIGER tracts zip |
| `Data/Clean/` | `permits.db` (SQLite) and `model/*.csv` (exported star schema) |
| `_working/` | `census_key.txt` (Census API key, keep private) and `refresh_log.txt` |

## Pipeline

`python Scripts/refresh.py` runs these in order, stops at the first failure, and appends one line to `_working/refresh_log.txt`:

1. `fetch_permits.py` saves the full permit layer to `Data/Raw/raw_<today>.json`. It refuses to overwrite an existing file, so it runs once per day. A count mismatch is saved as `raw_<today>.INCOMPLETE.json` and the run fails.
2. `load_permits.py` syncs the raw table `permits` to the newest complete raw file (adds new rows, removes vanished ones, keeps exact duplicates). It skips `*.INCOMPLETE.json`, and aborts without changes if the file would shrink the table by more than 5% (override with `PERMITS_ALLOW_SHRINK=1`). It also writes `load_log`.
3. `build_point_tract.py` assigns each distinct X/Y to a Wake County tract (`point_tract`). It needs geopandas and `Data/Raw/tiger/tl_2020_37_tract.zip`.
4. `build_clean.py` rebuilds `permits_clean`:
   - drops `row_hash`, `CONTRACTOR` and `MAILING_*`
   - collapses rows identical except OBJECTID
   - flags permit numbers that still repeat (`permit_number_repeats`)
   - trims DESCRIPTION and redacts phone numbers and email addresses in it (`[phone removed]`, `[email removed]`)
   - fills blank PROPOSED_USE with "Not recorded"
   - converts `*_DATE` epoch-ms values to ISO dates
   - sets `has_point`
5. `build_model.py` rebuilds `fact_permit`, `dim_date`, `dim_tract` and the category dimensions. It needs `tract_acs` from `fetch_acs.py` then `load_acs.py`, run separately when ACS data should refresh.
6. `export_model_csv.py` writes the 8 model tables to `Data/Clean/model/*.csv`. It writes temp files first and replaces them only if every row count matches.

Every script aborts with "Nothing changed" on bad input rather than writing partial output.

## Tests

```bash
python -m pytest Tests -q
python Tests/mutate.py build_clean.py load_permits.py build_model.py export_model_csv.py
```

Tests run the scripts as subprocesses against a temp database, using these environment variables (defaults are the real paths):

- `PERMITS_DB`: path to the SQLite database
- `PERMITS_WORK`: project root, used by `load_permits.py`
- `PERMITS_RAW`: raw folder, used by `load_permits.py`
- `PERMITS_ALLOW_SHRINK=1`: let `load_permits.py` load a pull that is more than 5% smaller than the table
- `PERMITS_URL`, `PERMITS_PAGE`, `PERMITS_WAIT`: endpoint, page size and retry wait (seconds) for `fetch_permits.py`; its tests run it against a local fake server

`mutate.py` is a small AST mutator: it swaps operators and constants, runs the suite per mutant, and lists survivors. Last run: all mutants killed except one unreachable error-message path in `export_model_csv.py`.

**Covered:** `fetch_permits`, `load_permits`, `build_clean`, `build_model`, `export_model_csv`.
**Not covered:** `fetch_acs`, `load_acs`, `build_point_tract`, `refresh`, and the `check_*` / `profile_*` helpers.

## Data security

- The Census key comes from the `CENSUS_API_KEY` environment variable, falling back to `_working/census_key.txt`. Neither is committed (see `.gitignore`).
- `Data/Raw/` and the `permits` table in `permits.db` still hold mailing addresses, contractors and unredacted descriptions. Share only `Data/Clean/model/*.csv`, which has none of these.
- `.gitignore` excludes raw data, databases, the model CSVs, logs and caches. Remove the `model/*.csv` line if you want to publish the CSVs.
- Install pinned dependencies with `pip install -r requirements.txt`.

## Known issues fixed

- `load_permits` could load an `.INCOMPLETE.json` pull and delete rows.
- `build_clean` aborted on pre-1970 dates on Windows.
