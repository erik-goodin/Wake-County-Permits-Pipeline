import json, os, sqlite3, subprocess, sys
from pathlib import Path
from hypothesis import given, settings, strategies as st, HealthCheck

WORK = Path(__file__).resolve().parent.parent / "Scripts"
SET = settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))

def run(script, tmp, *args):
    env = {**os.environ, "PERMITS_DB": str(tmp / "permits.db"), "PERMITS_WORK": str(tmp), "PERMITS_RAW": str(tmp / "raw")}
    return subprocess.run([sys.executable, str(WORK / script), *args], capture_output=True, stdin=subprocess.DEVNULL,
                          text=True, env=env, cwd=tmp)

def raw(tmp, rows, name="raw_2026-01-01.json"):
    p = tmp / name
    p.write_text(json.dumps({"pull_date": "2026-01-01",
                             "pages": [{"features": [{"attributes": r} for r in rows]}]}))
    return p

def rec(oid, pn="A", **kw):
    return {"OBJECTID": oid, "PERMIT_NUMBER": pn, "DESCRIPTION": "d", "PROPOSED_USE": "u",
            "X": 1.0, "Y": 2.0, "ISSUE_DATE": None, "CONTRACTOR": "c", "MAILING_CITY": "m", **kw}

def count(tmp, t="permits"):
    return sqlite3.connect(tmp / "permits.db").execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

def clean(tmp, rows):
    assert run("load_permits.py", tmp, str(raw(tmp, rows))).returncode == 0
    r = run("build_clean.py", tmp)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(tmp / "permits.db"); con.row_factory = sqlite3.Row
    return {x["OBJECTID"]: dict(x) for x in con.execute("SELECT * FROM permits_clean")}

def test_load_ignores_incomplete_file(tmp_path):
    (tmp_path / "raw").mkdir()
    raw(tmp_path / "raw", [rec(1), rec(2, "B")], "raw_2026-01-01.json")
    raw(tmp_path / "raw", [rec(1)], "raw_2026-01-02.INCOMPLETE.json")
    assert run("load_permits.py", tmp_path).returncode == 0
    assert count(tmp_path) == 2

def test_load_add_remove_idempotent(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1), rec(2, "B")])))
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1), rec(2, "B")])))
    assert count(tmp_path) == 2
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1), rec(3, "C")], "raw_b.json")))
    assert "added 1, removed 1" in r.stdout and count(tmp_path) == 2

def test_load_keeps_exact_duplicates(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1), rec(1)])))
    assert count(tmp_path) == 2

def test_load_rejects_field_change(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1)])))
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [{**rec(2), "NEW": 1}], "raw_b.json")))
    assert r.returncode != 0 and count(tmp_path) == 1

def test_clean_drops_columns_trims_defaults(tmp_path):
    c = clean(tmp_path, [rec(1, DESCRIPTION="  hi \n", PROPOSED_USE="  "), rec(2, "B", PROPOSED_USE=None)])
    assert "CONTRACTOR" not in c[1] and "MAILING_CITY" not in c[1] and "row_hash" not in c[1]
    assert c[1]["DESCRIPTION"] == "hi"
    assert c[1]["PROPOSED_USE"] == c[2]["PROPOSED_USE"] == "Not recorded"

def test_clean_dates(tmp_path):
    c = clean(tmp_path, [rec(1, ISSUE_DATE=1700000000000), rec(2, "B", ISSUE_DATE=-86400000),
                         rec(3, "C", ISSUE_DATE=86399999), rec(4, "D")])
    assert c[1]["ISSUE_DATE"] == "2023-11-14" and c[2]["ISSUE_DATE"] == "1969-12-31"
    assert c[3]["ISSUE_DATE"] == "1970-01-01" and c[4]["ISSUE_DATE"] is None

def test_clean_bad_date_aborts(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1, ISSUE_DATE="x")])))
    assert run("build_clean.py", tmp_path).returncode != 0
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1, ISSUE_DATE=10**18)], "raw_b.json")))
    assert run("build_clean.py", tmp_path).returncode != 0

def test_clean_has_point(tmp_path):
    c = clean(tmp_path, [rec(1, X=0, Y=5), rec(2, "B", X=5, Y=0), rec(3, "C", X=None), rec(4, "D", X=-1.5, Y=2),
                         rec(5, "E", X="1")])
    assert [c[i]["has_point"] for i in range(1, 6)] == [0, 0, 0, 1, 0]

def test_clean_collapse_and_flag(tmp_path):
    c = clean(tmp_path, [rec(5, "A"), rec(3, "A"), rec(9, "B", DESCRIPTION="x"), rec(8, "B", DESCRIPTION="y"),
                         rec(1, None), rec(2, "  "), rec(4, "D", CONTRACTOR="z"), rec(6, "D", CONTRACTOR="w")])
    assert set(c) == {3, 9, 8, 1, 2, 4}
    assert [c[i]["permit_number_repeats"] for i in (3, 9, 8, 1, 2, 4)] == [0, 1, 1, 0, 0, 0]

def test_clean_duplicate_objectid_aborts(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1, "A"), rec(1, "B")])))
    assert run("build_clean.py", tmp_path).returncode != 0
    assert not sqlite3.connect(tmp_path / "permits.db").execute(
        "SELECT 1 FROM sqlite_master WHERE name='permits_clean'").fetchone()

def test_clean_missing_column_aborts(tmp_path):
    r = [rec(1)]; del r[0]["PROPOSED_USE"]
    run("load_permits.py", tmp_path, str(raw(tmp_path, r)))
    assert run("build_clean.py", tmp_path).returncode != 0

@SET
@given(st.lists(st.tuples(st.integers(0, 4), st.sampled_from(["a", "b", None]),
                          st.one_of(st.none(), st.integers(-10**11, 4 * 10**12))), max_size=12, unique_by=lambda t: None))
def test_prop_clean_invariants(tmp_path_factory, items):
    tmp = tmp_path_factory.mktemp("h")
    rows = [rec(i + 1, f"P{p}", DESCRIPTION=f" {d} ", ISSUE_DATE=dt) for i, (p, d, dt) in enumerate(items)]
    if not rows:
        return
    c = clean(tmp, rows)
    assert len({(r["PERMIT_NUMBER"]) for r in c.values()}) <= len({r["PERMIT_NUMBER"] for r in rows})
    for r in c.values():
        assert r["DESCRIPTION"] == r["DESCRIPTION"].strip()
        assert r["ISSUE_DATE"] is None or len(r["ISSUE_DATE"]) == 10
    # idempotent rebuild
    run("build_clean.py", tmp)
    assert count(tmp, "permits_clean") == len(c)

def test_load_summary_and_multicopy_removal(tmp_path):
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1)] * 3 + [rec(2, "B")])))
    assert "added 4, removed 0, rows now 4, table matches source: True" in r.stdout
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1), rec(2, "B")] + [rec(3, "C")] * 2, "raw_b.json")))
    assert "added 2, removed 2, rows now 4, table matches source: True" in r.stdout
    assert count(tmp_path) == 4

def test_load_field_change_message(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1)])))
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [{**rec(2), "NEW": 1}], "raw_b.json")))
    assert "In file only: ['NEW']" in r.stderr and "In table only: []" in r.stderr
    run("load_permits.py", tmp_path, str(raw(tmp_path, [{k: v for k, v in rec(2).items() if k != "X"}], "raw_c.json")))
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [{k: v for k, v in rec(2).items() if k != "X"}], "raw_c.json")))
    assert "In table only: ['X']" in r.stderr

def test_clean_summary_and_types(tmp_path):
    rows = [rec(1, DESCRIPTION=" a", PROPOSED_USE=None, ISSUE_DATE=0, SQUARE_FEET=1.5, N=3, S="s"),
            rec(2, "B", DESCRIPTION=None, PROPOSED_USE=" ", ISSUE_DATE=5, SQUARE_FEET=2, N=None, S=None),
            rec(3, "C", DESCRIPTION=None, PROPOSED_USE="ok", SQUARE_FEET=2, N=1, S="t")]
    clean(tmp_path, rows)
    out = run("build_clean.py", tmp_path).stdout
    assert "rows read: 3, distinct without mailing fields: 3" in out
    assert "rows kept: 3, collapsed (identical except OBJECTID): 0" in out
    assert "PERMIT_NUMBERs still on more than one row: 0, flagged rows: 0" in out
    assert "DESCRIPTION trimmed: 1" in out
    assert "PROPOSED_USE set to 'Not recorded': 1 null, 1 whitespace-only" in out
    assert "dates converted: ISSUE_DATE 2" in out
    assert "has_point 1: 3, 0: 0" in out and "permits_clean rows: 3, matches kept rows: True" in out
    types = {r[1]: r[2] for r in sqlite3.connect(tmp_path / "permits.db").execute("PRAGMA table_info(permits_clean)")}
    assert types["ISSUE_DATE"] == "TEXT" and types["SQUARE_FEET"] == "REAL" and types["N"] == "INTEGER"
    assert types["S"] == "TEXT" and types["OBJECTID"] == "INTEGER"

def test_clean_collapse_summary(tmp_path):
    clean(tmp_path, [rec(1), rec(2), rec(3, "B", DESCRIPTION="x"), rec(4, "B", DESCRIPTION="y"),
                     rec(5, "C", DESCRIPTION="x"), rec(6, "C", DESCRIPTION="y"), rec(7, "C", DESCRIPTION="z")])
    out = run("build_clean.py", tmp_path).stdout
    assert "collapsed (identical except OBJECTID): 1" in out
    assert "still on more than one row: 2, flagged rows: 5" in out

def test_load_added_counts_only_new_copies(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1)])))
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1)] * 3, "raw_b.json")))
    assert "added 2, removed 0, rows now 3" in r.stdout

def test_clean_bad_date_message(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, [rec(1, ISSUE_DATE="x")])))
    assert "Non-numeric value in ISSUE_DATE" in run("build_clean.py", tmp_path).stderr

def test_clean_no_points_summary(tmp_path):
    clean(tmp_path, [rec(1, X=0)])
    assert "has_point 1: 0, 0: 1" in run("build_clean.py", tmp_path).stdout

def test_clean_collapse_key_includes_column_after_objectid(tmp_path):
    def r(oid, d):
        return {"PERMIT_NUMBER": "A", "OBJECTID": oid, "DESCRIPTION": d, "PROPOSED_USE": "u", "X": 1, "Y": 2}
    c = clean(tmp_path, [r(1, "x"), r(2, "y")])
    assert set(c) == {1, 2} and c[1]["permit_number_repeats"] == 1

def test_clean_redacts_contact_info(tmp_path):
    ds = ["call 919-557-3908 now", "ph (919) 469.4082 or 919 856 6335", "mail Bob.X+1@yahoo.com, or a@b.co.",
          "no pii 24X48 deck, 12345 sq ft, permit 2020-123-4567", "x@y"]
    c = clean(tmp_path, [rec(i + 1, f"P{i}", DESCRIPTION=d) for i, d in enumerate(ds)])
    assert c[1]["DESCRIPTION"] == "call [phone removed] now"
    assert c[2]["DESCRIPTION"] == "ph [phone removed] or [phone removed]"
    assert c[3]["DESCRIPTION"] == "mail [email removed], or [email removed]."
    assert c[4]["DESCRIPTION"] == ds[3] and c[5]["DESCRIPTION"] == "x@y"
    out = run("build_clean.py", tmp_path).stdout
    assert "DESCRIPTION contact details redacted: 3" in out
    assert "DESCRIPTION trimmed: 0" in out

def test_clean_redaction_idempotent_and_none_safe(tmp_path):
    c = clean(tmp_path, [rec(1, DESCRIPTION=None), rec(2, "B", DESCRIPTION="[phone removed] [email removed]")])
    assert c[1]["DESCRIPTION"] is None and c[2]["DESCRIPTION"] == "[phone removed] [email removed]"

def _rows(n):
    return [rec(i, f"P{i}") for i in range(1, n + 1)]

def test_load_aborts_on_big_shrink(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(20))))
    r = run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(18), "raw_b.json")))
    assert r.returncode != 0 and "shrinks the table from 20 to 18" in r.stderr and "Nothing changed" in r.stderr
    assert count(tmp_path) == 20
    assert count(tmp_path, "load_log") == 1

def test_load_allows_five_percent_shrink_and_growth(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(20))))
    assert run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(19), "raw_b.json"))).returncode == 0
    assert count(tmp_path) == 19
    assert run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(40), "raw_c.json"))).returncode == 0
    assert count(tmp_path) == 40

def test_load_empty_source_aborts_but_override_works(tmp_path):
    run("load_permits.py", tmp_path, str(raw(tmp_path, _rows(5))))
    p = raw(tmp_path, [], "raw_b.json")
    assert run("load_permits.py", tmp_path, str(p)).returncode != 0 and count(tmp_path) == 5
    env = {**os.environ, "PERMITS_DB": str(tmp_path / "permits.db"), "PERMITS_WORK": str(tmp_path),
           "PERMITS_ALLOW_SHRINK": "1"}
    r = subprocess.run([sys.executable, str(WORK / "load_permits.py"), str(raw(tmp_path, _rows(2), "raw_c.json"))],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 0 and "removed 3" in r.stdout and count(tmp_path) == 2
