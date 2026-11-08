"""Tiny mutation tester: python Tests/mutate.py build_clean.py load_permits.py"""
import ast, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
W = Path(__file__).resolve().parent.parent / "Scripts"
CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.GtE: ast.Lt,
       ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add, ast.Div: ast.Mult}

def sites(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            for i, o in enumerate(n.ops):
                if type(o) in CMP: yield n, "op", i
        elif isinstance(n, ast.BinOp) and type(n.op) in BIN: yield n, "bin", 0
        elif isinstance(n, ast.BoolOp): yield n, "bool", 0
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not): yield n, "not", 0
        elif isinstance(n, ast.Constant) and type(n.value) is int and n.value in (0, 1, 1000): yield n, "int", 0
        elif isinstance(n, ast.Constant) and n.value == "Not recorded": yield n, "str", 0

def apply(n, kind, i):
    if kind == "op": n.ops[i] = CMP[type(n.ops[i])]()
    elif kind == "bin": n.op = BIN[type(n.op)]()
    elif kind == "bool": n.op = ast.Or() if isinstance(n.op, ast.And) else ast.And()
    elif kind == "not": n.__class__ = ast.Expr; n.value = n.operand  # drop negation (placeholder, fixed below)
    elif kind == "int": n.value += 1
    elif kind == "str": n.value = "XX"

def mutants(f):
    src = (W / f).read_text(encoding="utf-8"); count = len(list(sites(ast.parse(src))))
    for k in range(count):
        t = ast.parse(src); n, kind, i = list(sites(t))[k]
        if kind == "not":
            continue
        apply(n, kind, i); ast.fix_missing_locations(t)
        yield f, k, getattr(n, "lineno", 0), kind, ast.unparse(t)

def test(m):
    f, k, line, kind, code = m
    d = Path(tempfile.mkdtemp())
    (d / "Scripts").mkdir()
    for s in W.glob("*.py"): shutil.copy(s, d / "Scripts")
    shutil.copytree(W.parent / "Tests", d / "Tests", ignore=shutil.ignore_patterns("__pycache__", ".hypothesis", ".pytest_cache"))
    (d / "Scripts" / f).write_text(code, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "Tests", "-q", "-x", "-p", "no:cacheprovider", "-k", "not prop"],
                       cwd=d, capture_output=True, stdin=subprocess.DEVNULL)
    shutil.rmtree(d, ignore_errors=True)
    return m, r.returncode != 0

if __name__ == "__main__":
    ms = [m for f in sys.argv[1:] for m in mutants(f)]
    with ThreadPoolExecutor(4) as ex: res = list(ex.map(test, ms))
    surv = [m for m, killed in res if not killed]
    print(f"mutants {len(ms)}, killed {len(ms) - len(surv)}, survived {len(surv)}")
    for f, k, line, kind, _ in surv: print(f"SURVIVED {f}:{line} {kind}")
