import os, sqlite3, sys
from datetime import date, timedelta
from pathlib import Path

DB = Path(os.environ.get("PERMITS_DB", Path(__file__).resolve().parent.parent / "Data" / "Clean" / "permits.db"))
con = sqlite3.connect(DB)

have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
for t, step in (("permits_clean", "build_clean.py"), ("point_tract", "build_point_tract.py"),
                ("tract_acs", "load_acs.py")):
    if t not in have:
        sys.exit(f"Table {t} is missing. Run {step} first. Nothing changed.")
cols = {r[1] for r in con.execute("PRAGMA table_info(permits_clean)")}
need = {"OBJECTID", "PERMIT_NUMBER", "APPLICATION_DATE", "ISSUE_DATE", "FINALED_DATE", "EXPIRATION_DATE",
        "PERMIT_TYPE", "WORK_CLASS", "PERMIT_STATUS", "DISTRICT", "PROPOSED_USE", "SQUARE_FEET",
        "VALUATION", "TOTAL_FEE_AMOUNT", "DESCRIPTION", "LINK", "PIN", "X", "Y",
        "has_point", "permit_number_repeats"}
if need - cols:
    sys.exit(f"permits_clean is missing {sorted(need - cols)}. Nothing changed.")

DIMS = [("permit_type", "PERMIT_TYPE"), ("work_class", "WORK_CLASS"), ("permit_status", "PERMIT_STATUS"),
        ("district", "DISTRICT"), ("proposed_use", "PROPOSED_USE")]
DATES = ["APPLICATION_DATE", "ISSUE_DATE", "FINALED_DATE", "EXPIRATION_DATE"]

lo = hi = None
for c in DATES:
    a, b = con.execute(f"SELECT MIN({c}), MAX({c}) FROM permits_clean").fetchone()
    if a:
        lo = a if lo is None or a < lo else lo
        hi = b if hi is None or b > hi else hi
if lo is None:
    sys.exit("No dates found in permits_clean. Nothing changed.")
d, end = date.fromisoformat(lo), date.fromisoformat(hi)
days = []
while d <= end:
    days.append((d.isoformat(), d.year, d.month, d.strftime("%B"), (d.month - 1) // 3 + 1,
                 d.strftime("%Y-%m")))
    d += timedelta(days=1)

with con:
    for t in ["fact_permit", "dim_date", "dim_tract"] + [f"dim_{n}" for n, _ in DIMS]:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    for n, c in DIMS:
        con.execute(f"CREATE TABLE dim_{n} ({n}_key INTEGER PRIMARY KEY, {n} TEXT NOT NULL UNIQUE)")
        con.execute(f"INSERT INTO dim_{n} ({n}) SELECT DISTINCT COALESCE({c}, 'Unknown') FROM permits_clean "
                    f"ORDER BY 1")
    con.execute("CREATE TABLE dim_tract (tract_id TEXT PRIMARY KEY, tract_name TEXT, population REAL, "
                "population_moe REAL, median_income REAL, median_income_moe REAL)")
    con.execute("INSERT INTO dim_tract SELECT tract_id, tract_name, population, population_moe, "
                "median_income, median_income_moe FROM tract_acs")
    con.execute("CREATE TABLE dim_date (date TEXT PRIMARY KEY, year INTEGER, month INTEGER, month_name TEXT, "
                "quarter INTEGER, year_month TEXT)")
    con.executemany("INSERT INTO dim_date VALUES (?, ?, ?, ?, ?, ?)", days)
    con.execute("""CREATE TABLE fact_permit (
        object_id INTEGER PRIMARY KEY, permit_number TEXT,
        application_date TEXT, issue_date TEXT, finaled_date TEXT, expiration_date TEXT,
        permit_type_key INTEGER, work_class_key INTEGER, permit_status_key INTEGER,
        district_key INTEGER, proposed_use_key INTEGER, tract_id TEXT,
        square_feet REAL, valuation REAL, total_fee_amount REAL,
        has_point INTEGER, permit_number_repeats INTEGER,
        description TEXT, link TEXT, pin TEXT, x REAL, y REAL)""")
    joins = " ".join(f"LEFT JOIN dim_{n} ON dim_{n}.{n} = COALESCE(c.{c}, 'Unknown')" for n, c in DIMS)
    con.execute(f"""INSERT INTO fact_permit
        SELECT c.OBJECTID, c.PERMIT_NUMBER, c.APPLICATION_DATE, c.ISSUE_DATE, c.FINALED_DATE, c.EXPIRATION_DATE,
               dim_permit_type.permit_type_key, dim_work_class.work_class_key, dim_permit_status.permit_status_key,
               dim_district.district_key, dim_proposed_use.proposed_use_key, p.tract_id,
               c.SQUARE_FEET, c.VALUATION, c.TOTAL_FEE_AMOUNT, c.has_point, c.permit_number_repeats,
               c.DESCRIPTION, c.LINK, c.PIN, c.X, c.Y
        FROM permits_clean c {joins}
        LEFT JOIN point_tract p ON c.has_point = 1 AND p.x = c.X AND p.y = c.Y""")

q = lambda s: con.execute(s).fetchone()[0]
print("dimension rows: " + ", ".join(f"dim_{n} {q(f'SELECT COUNT(*) FROM dim_{n}')}" for n, _ in DIMS)
      + f", dim_tract {q('SELECT COUNT(*) FROM dim_tract')}, dim_date {q('SELECT COUNT(*) FROM dim_date')}")
n_f, n_c = q("SELECT COUNT(*) FROM fact_permit"), q("SELECT COUNT(*) FROM permits_clean")
print(f"fact_permit rows: {n_f}, permits_clean rows: {n_c}, match: {n_f == n_c}")
print("fact rows missing a category key: " + str(q(
    "SELECT COUNT(*) FROM fact_permit WHERE permit_type_key IS NULL OR work_class_key IS NULL "
    "OR permit_status_key IS NULL OR district_key IS NULL OR proposed_use_key IS NULL")))
print(f"fact rows with a tract: {q('SELECT COUNT(*) FROM fact_permit WHERE tract_id IS NOT NULL')}, "
      f"with a point but no tract: {q('SELECT COUNT(*) FROM fact_permit WHERE has_point = 1 AND tract_id IS NULL')}, "
      f"with no point: {q('SELECT COUNT(*) FROM fact_permit WHERE has_point = 0')}")
print("tract IDs in fact_permit but not in dim_tract: " + str(q(
    "SELECT COUNT(DISTINCT tract_id) FROM fact_permit WHERE tract_id IS NOT NULL "
    "AND tract_id NOT IN (SELECT tract_id FROM dim_tract)")))
print("fact dates not in dim_date: " + str(sum(q(
    f"SELECT COUNT(*) FROM fact_permit WHERE {c.lower()} IS NOT NULL AND {c.lower()} NOT IN (SELECT date FROM dim_date)")
    for c in DATES)))
same = all(q(f"SELECT ROUND(COALESCE(SUM({a}), 0), 2) FROM fact_permit") ==
           q(f"SELECT ROUND(COALESCE(SUM({b}), 0), 2) FROM permits_clean")
           for a, b in (("valuation", "VALUATION"), ("square_feet", "SQUARE_FEET"),
                        ("total_fee_amount", "TOTAL_FEE_AMOUNT")))
print(f"valuation, square feet and fee totals match permits_clean: {same}")
con.close()
