import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_pipeline import run

def setup(tmp, rows, tracts=(("T1", "Tract 1", 100.0, 5.0, 50000.0, 900.0),), points=(), acs=True):
    con = sqlite3.connect(tmp / "permits.db")
    con.execute("""CREATE TABLE permits_clean (OBJECTID INTEGER PRIMARY KEY, PERMIT_NUMBER, APPLICATION_DATE,
        ISSUE_DATE, FINALED_DATE, EXPIRATION_DATE, PERMIT_TYPE, WORK_CLASS, PERMIT_STATUS, DISTRICT, PROPOSED_USE,
        SQUARE_FEET, VALUATION, TOTAL_FEE_AMOUNT, DESCRIPTION, LINK, PIN, X, Y, has_point, permit_number_repeats)""")
    con.execute("CREATE TABLE point_tract (x REAL, y REAL, tract_id TEXT)")
    if acs:
        con.execute("CREATE TABLE tract_acs (tract_id, tract_name, population, population_moe, median_income, median_income_moe)")
        con.executemany("INSERT INTO tract_acs VALUES (?,?,?,?,?,?)", tracts)
    con.executemany("INSERT INTO point_tract VALUES (?,?,?)", points)
    base = dict(PERMIT_NUMBER="A", APPLICATION_DATE="2020-01-31", ISSUE_DATE=None, FINALED_DATE=None, EXPIRATION_DATE=None,
                PERMIT_TYPE="Building", WORK_CLASS="New", PERMIT_STATUS="Open", DISTRICT="D1", PROPOSED_USE="Home",
                SQUARE_FEET=10.0, VALUATION=100.5, TOTAL_FEE_AMOUNT=1.25, DESCRIPTION="d", LINK="l", PIN="p",
                X=1.0, Y=2.0, has_point=1, permit_number_repeats=0)
    for i, r in enumerate(rows, 1):
        d = {**base, "OBJECTID": i, **r}
        con.execute(f"INSERT INTO permits_clean ({','.join(d)}) VALUES ({','.join('?' * len(d))})", list(d.values()))
    con.commit()
    return con

def model(tmp):
    r = run("build_model.py", tmp)
    return r, sqlite3.connect(tmp / "permits.db")

def test_missing_table_aborts(tmp_path):
    setup(tmp_path, [{}], acs=False)
    r, _ = model(tmp_path)
    assert r.returncode != 0 and "tract_acs is missing" in r.stderr and "load_acs.py" in r.stderr

def test_missing_column_aborts(tmp_path):
    con = setup(tmp_path, [{}]); con.execute("ALTER TABLE permits_clean DROP COLUMN PIN"); con.commit()
    r, c = model(tmp_path)
    assert r.returncode != 0 and "['PIN']" in r.stderr
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='fact_permit'").fetchone()

def test_no_dates_aborts(tmp_path):
    setup(tmp_path, [{"APPLICATION_DATE": None}])
    assert "No dates found" in model(tmp_path)[0].stderr

def test_dim_date_range_and_attrs(tmp_path):
    setup(tmp_path, [{"APPLICATION_DATE": "2020-01-31", "EXPIRATION_DATE": "2020-04-02"}])
    r, c = model(tmp_path)
    assert r.returncode == 0, r.stderr
    rows = c.execute("SELECT * FROM dim_date ORDER BY date").fetchall()
    assert len(rows) == 63 and rows[0] == ("2020-01-31", 2020, 1, "January", 1, "2020-01") and rows[-1][0] == "2020-04-02"
    assert c.execute("SELECT quarter FROM dim_date WHERE date='2020-04-01'").fetchone()[0] == 2
    assert c.execute("SELECT quarter FROM dim_date WHERE date='2020-03-31'").fetchone()[0] == 1

def test_dim_date_min_max_across_columns(tmp_path):
    setup(tmp_path, [{"APPLICATION_DATE": "2020-02-10", "ISSUE_DATE": "2020-02-05", "FINALED_DATE": "2020-02-20"},
                     {"APPLICATION_DATE": "2020-02-12", "EXPIRATION_DATE": "2020-02-25"}])
    _, c = model(tmp_path)
    assert c.execute("SELECT MIN(date), MAX(date) FROM dim_date").fetchone() == ("2020-02-05", "2020-02-25")

def test_fact_matches_clean_and_keys(tmp_path):
    setup(tmp_path, [{"PERMIT_TYPE": "Building"}, {"PERMIT_TYPE": None, "DISTRICT": None, "PROPOSED_USE": "Shop"},
                     {"PERMIT_TYPE": "Building", "WORK_CLASS": "Alter"}])
    r, c = model(tmp_path)
    assert c.execute("SELECT COUNT(*) FROM fact_permit").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM fact_permit WHERE permit_type_key IS NULL OR district_key IS NULL").fetchone()[0] == 0
    assert c.execute("SELECT permit_type FROM dim_permit_type ORDER BY 1").fetchall() == [("Building",), ("Unknown",)]
    q = ("SELECT d.permit_type FROM fact_permit f JOIN dim_permit_type d USING (permit_type_key) WHERE object_id=2")
    assert c.execute(q).fetchone()[0] == "Unknown"
    assert "fact_permit rows: 3, permits_clean rows: 3, match: True" in r.stdout
    assert "rows missing a category key: 0" in r.stdout
    assert "totals match permits_clean: True" in r.stdout

def test_tract_join_only_with_point(tmp_path):
    setup(tmp_path, [{"X": 1.0, "Y": 2.0}, {"X": 1.0, "Y": 2.0, "has_point": 0}, {"X": 9.0, "Y": 9.0}],
          points=[(1.0, 2.0, "T1"), (9.0, 9.0, None)])
    r, c = model(tmp_path)
    assert c.execute("SELECT object_id, tract_id FROM fact_permit ORDER BY 1").fetchall() == [(1, "T1"), (2, None), (3, None)]
    assert "with a tract: 1, with a point but no tract: 1, with no point: 1" in r.stdout

def test_unknown_tract_and_missing_date_reported(tmp_path):
    setup(tmp_path, [{}], points=[(1.0, 2.0, "ZZ")])
    assert "tract IDs in fact_permit but not in dim_tract: 1" in model(tmp_path)[0].stdout

def test_rebuild_idempotent_and_totals(tmp_path):
    setup(tmp_path, [{"VALUATION": 0.1}, {"VALUATION": 0.2}, {"VALUATION": None}])
    model(tmp_path); r, c = model(tmp_path)
    assert r.returncode == 0 and c.execute("SELECT COUNT(*) FROM fact_permit").fetchone()[0] == 3
    assert abs(c.execute("SELECT SUM(valuation) FROM fact_permit").fetchone()[0] - 0.3) < 1e-9
    assert c.execute("SELECT permit_number, link, pin, x, y FROM fact_permit WHERE object_id=1").fetchone() == ("A", "l", "p", 1.0, 2.0)
    assert "dimension rows: dim_permit_type 1" in r.stdout and "dim_tract 1, dim_date 1" in r.stdout
