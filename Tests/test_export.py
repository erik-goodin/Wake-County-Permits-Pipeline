import csv, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_pipeline import run

TABLES = ["fact_permit", "dim_permit_type", "dim_work_class", "dim_permit_status", "dim_district",
          "dim_proposed_use", "dim_tract", "dim_date"]

def setup(tmp, skip=()):
    con = sqlite3.connect(tmp / "permits.db")
    for t in TABLES:
        if t in skip:
            continue
        con.execute(f"CREATE TABLE {t} (id INTEGER, name TEXT)")
        con.executemany(f"INSERT INTO {t} VALUES (?, ?)", [(1, "a,b"), (2, None), (3, 'q"x\nnl')])
    con.commit(); con.close()

def read(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))

def test_exports_all_tables(tmp_path):
    setup(tmp_path)
    r = run("export_model_csv.py", tmp_path)
    assert r.returncode == 0, r.stderr
    for t in TABLES:
        assert read(tmp_path / "model" / f"{t}.csv") == [["id", "name"], ["1", "a,b"], ["2", ""], ["3", 'q"x\nnl']]
        assert f"{t}: 3 rows written, 3 rows in table" in r.stdout
    assert "model CSV files written: 8, counts match: True" in r.stdout
    assert not list((tmp_path / "model").glob("*.tmp"))

def test_missing_table_aborts_without_output(tmp_path):
    setup(tmp_path, skip=("dim_date",))
    r = run("export_model_csv.py", tmp_path)
    assert r.returncode != 0 and "Table dim_date is missing" in r.stderr and "build_model.py" in r.stderr
    assert not (tmp_path / "model").exists()

def test_rerun_overwrites(tmp_path):
    setup(tmp_path); run("export_model_csv.py", tmp_path)
    con = sqlite3.connect(tmp_path / "permits.db"); con.execute("DELETE FROM fact_permit WHERE id = 1"); con.commit(); con.close()
    assert run("export_model_csv.py", tmp_path).returncode == 0
    assert len(read(tmp_path / "model" / "fact_permit.csv")) == 3
    assert len(read(tmp_path / "model" / "dim_date.csv")) == 4

def test_empty_table(tmp_path):
    setup(tmp_path)
    con = sqlite3.connect(tmp_path / "permits.db"); con.execute("DELETE FROM dim_tract"); con.commit(); con.close()
    assert run("export_model_csv.py", tmp_path).returncode == 0
    assert read(tmp_path / "model" / "dim_tract.csv") == [["id", "name"]]
