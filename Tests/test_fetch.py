import json, os, socket, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "Scripts" / "fetch_permits.py"


class Fake:
    """Local fake ArcGIS endpoint with scripted failures."""

    def __init__(self, n=5, cap=2, count=None, failures=(), flag=True, body=None):
        self.n, self.cap, self.count, self.failures, self.flag, self.body = n, cap, count, list(failures), flag, body
        self.log = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                fake.log.append(q)
                if fake.failures:
                    f = fake.failures.pop(0)
                    if isinstance(f, int):
                        self.send_response(f)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    return self.reply(200, f, raw=True)
                if fake.body is not None:
                    return self.reply(200, fake.body)
                if q.get("returnCountOnly") == "true":
                    return self.reply(200, {"count": fake.n if fake.count is None else fake.count})
                off, want = int(q["resultOffset"]), min(int(q["resultRecordCount"]), fake.cap)
                ids = list(range(1, fake.n + 1))[off:off + want]
                out = {"features": [{"attributes": {"OBJECTID": i}} for i in ids]}
                if fake.flag and off + len(ids) < fake.n:
                    out["exceededTransferLimit"] = True
                self.reply(200, out)

            def reply(self, code, obj, raw=False):
                data = (obj if raw else json.dumps(obj)).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/query"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def data_calls(self):
        return [q for q in self.log if "returnCountOnly" not in q]


@pytest.fixture
def fake(request):
    f = Fake(**getattr(request, "param", {}))
    yield f
    f.close()


def fetch(url, out, page=2, wait="0.01"):
    env = {**os.environ, "PERMITS_URL": url, "PERMITS_PAGE": str(page), "PERMITS_WAIT": wait}
    return subprocess.run([sys.executable, str(SCRIPT), str(out)], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, env=env, timeout=60)


def files(out):
    return sorted(p.name for p in out.glob("*")) if out.exists() else []


def saved(out):
    (p,) = [p for p in out.glob("raw_*.json") if "INCOMPLETE" not in p.name]
    return json.loads(p.read_text())


def test_multi_page_ok(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode == 0, r.stderr
    d = saved(tmp_path)
    assert d["expected_count"] == 5 and d["saved_count"] == 5 and len(d["pages"]) == 3
    assert [f["attributes"]["OBJECTID"] for p in d["pages"] for f in p["features"]] == [1, 2, 3, 4, 5]
    assert "expected 5, saved 5, match: True" in r.stdout
    assert len(files(tmp_path)) == 1 and not list(tmp_path.glob("*.tmp"))
    c = fake.data_calls()[0]
    assert c["orderByFields"] == "OBJECTID" and c["outFields"] == "*" and c["returnGeometry"] == "false"
    assert [q["resultOffset"] for q in fake.data_calls()] == ["0", "2", "4"]


@pytest.mark.parametrize("fake", [dict(n=5, cap=2)], indirect=True)
def test_server_cap_below_page(fake, tmp_path):
    assert fetch(fake.url, tmp_path, page=100).returncode == 0
    assert saved(tmp_path)["saved_count"] == 5


@pytest.mark.parametrize("fake", [dict(n=4, cap=2)], indirect=True)
def test_exact_multiple_of_page_stops(fake, tmp_path):
    assert fetch(fake.url, tmp_path).returncode == 0
    assert saved(tmp_path)["saved_count"] == 4 and len(fake.data_calls()) == 2


@pytest.mark.parametrize("fake", [dict(n=5, count=7)], indirect=True)
def test_count_mismatch_saved_as_incomplete(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and "Count mismatch" in r.stderr and "match: False" in r.stdout
    (name,) = files(tmp_path)
    assert name.endswith(".INCOMPLETE.json")
    assert json.loads((tmp_path / name).read_text())["saved_count"] == 5


@pytest.mark.parametrize("fake", [dict(n=5, count=4)], indirect=True)
def test_extra_rows_also_mismatch(fake, tmp_path):
    assert fetch(fake.url, tmp_path).returncode != 0
    assert files(tmp_path)[0].endswith(".INCOMPLETE.json")


@pytest.mark.parametrize("fake", [dict(n=5, cap=2, flag=False)], indirect=True)
def test_missing_transfer_flag_stops_and_marks_incomplete(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and files(tmp_path)[0].endswith(".INCOMPLETE.json") and len(fake.data_calls()) == 1


@pytest.mark.parametrize("fake", [dict(n=0)], indirect=True)
def test_zero_count_saves_nothing(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and "Count is 0" in r.stderr and files(tmp_path) == [] and fake.data_calls() == []


def test_existing_file_not_overwritten(fake, tmp_path):
    assert fetch(fake.url, tmp_path).returncode == 0
    (p,) = tmp_path.glob("raw_*.json")
    before, calls = p.read_text(), len(fake.log)
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and "already exists" in r.stderr and p.read_text() == before and len(fake.log) == calls


def test_creates_output_dir(fake, tmp_path):
    assert fetch(fake.url, tmp_path / "a" / "b").returncode == 0 and len(files(tmp_path / "a" / "b")) == 1


@pytest.mark.parametrize("fake", [dict(failures=[503, 429, "<html>oops</html>"])], indirect=True)
def test_retries_then_succeeds(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode == 0, r.stderr
    assert [l for l in r.stdout.splitlines() if "Retrying" in l] == [
        "Request failed (HTTP 503). Retrying in 0.01s.", "Request failed (HTTP 429). Retrying in 0.02s.",
        "Request failed (InvalidJSON). Retrying in 0.04s."]
    assert saved(tmp_path)["saved_count"] == 5


@pytest.mark.parametrize("fake", [dict(failures=[500, 502, 504, 503])], indirect=True)
def test_retries_exhausted(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and "Failed after 3 retries: HTTP 503" in r.stderr
    assert len(fake.log) == 4 and files(tmp_path) == []


@pytest.mark.parametrize("fake", [dict(failures=[404])], indirect=True)
def test_client_error_not_retried(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and len(fake.log) == 1 and "Retrying" not in r.stdout


@pytest.mark.parametrize("fake", [dict(body={"error": {"code": 400, "message": "bad"}})], indirect=True)
def test_api_error_not_retried(fake, tmp_path):
    r = fetch(fake.url, tmp_path)
    assert r.returncode != 0 and "API error" in r.stderr and len(fake.log) == 1


def test_connection_error_retried_then_fails(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = fetch(f"http://127.0.0.1:{port}/query", tmp_path)
    assert r.returncode != 0 and "Failed after 3 retries: ConnectionError" in r.stderr
    assert r.stdout.count("Retrying") == 3 and files(tmp_path) == []
