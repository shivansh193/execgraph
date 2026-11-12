"""In-process tracer, run by trace_failure.py under the task's Python.

    python _tracer.py OUT_JSON REPO pytest [pytest args...]
    python _tracer.py OUT_JSON REPO script PATH [script args...]

Records which repo functions each test executes (set per test, not counts), each test's outcome, and the
traceback of every failure with short local-variable summaries. Uses sys.monitoring on 3.12+ (one event per
function per test, then DISABLE), sys.setprofile otherwise. Stdlib only.
"""
import json
import linecache
import os
import sys
import threading
import time
import traceback

OUT, REPO = sys.argv[1], os.path.realpath(sys.argv[2])
MODE, ARGS = sys.argv[3], sys.argv[4:]
SKIP_DIRS = ("site-packages", "dist-packages", "/.venv/", "/venv/", "/.tox/", "/.git/", "/node_modules/")
LIB_PREFIXES = tuple({os.path.realpath(p) + os.sep for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)})

_is_repo = {}   # filename -> bool
_ids = {}       # code -> (node id, file, firstline)
cur = None      # code -> first-run order, for the running test
direct = set()  # codes called directly from test code in the running test
calls = {}      # code -> nearest repo/test caller code, at its first run in the running test
reporting = False
tests = {}      # test id -> {"outcome", "codes", "direct", "calls"}
failures = []


def repo_file(fn):
    r = _is_repo.get(fn)
    if r is None:
        p = os.path.realpath(fn) if fn and not fn.startswith("<") else ""
        r = bool(p) and p.startswith(REPO + os.sep) and not any(s in p for s in SKIP_DIRS)
        _is_repo[fn] = r
    return r


def module_of(path):
    rel = os.path.relpath(os.path.realpath(path), REPO)
    if rel.endswith(".py"):
        rel = rel[:-3]
    parts = rel.replace(os.sep, "/").split("/")
    if parts[0] in ("src", "lib") and len(parts) > 1:
        parts = parts[1:]
    if parts[0] == "docs_src" and len(parts) > 1:   # the competition graph strips docs_src.
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


_quals = {}     # filename -> {first line of a def or its decorators: qualified name}


def qualname_by_line(filename, lineno, name):
    """Python < 3.11 has no co_qualname: recover `Class.method` from the source by the def's first line (the
    first decorator's line on 3.8+). Falls back to the bare name."""
    idx = _quals.get(filename)
    if idx is None:
        idx = {}
        try:
            import ast
            tree = ast.parse(open(filename, encoding="utf-8", errors="replace").read())

            def walk(body, prefix):
                for n in body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        q = prefix + n.name
                        for ln in [n.lineno] + [d.lineno for d in n.decorator_list]:
                            idx.setdefault(ln, q)
                        walk(n.body, q + (".<locals>." if not isinstance(n, ast.ClassDef) else "."))
                    elif hasattr(n, "body") and isinstance(n.body, list):
                        walk(n.body, prefix)
                        for attr in ("orelse", "finalbody", "handlers"):
                            sub = getattr(n, attr, None)
                            if isinstance(sub, list):
                                walk(sub, prefix)
            walk(tree.body, "")
        except Exception:  # noqa: BLE001
            pass
        _quals[filename] = idx
    q = idx.get(lineno)
    return q if q and q.rsplit(".", 1)[-1] == name else name


def node_of(code):
    v = _ids.get(code)
    if v is None:
        qual = getattr(code, "co_qualname", None) or qualname_by_line(code.co_filename, code.co_firstlineno, code.co_name)
        if ".<locals>" in qual:              # nested function or comprehension -> enclosing function
            qual = qual.split(".<locals>")[0]
        if qual.startswith("<"):            # <module>, top-level <lambda>/<genexpr>
            qual = ""
        mod = module_of(code.co_filename)
        # Module and class bodies have no CO_NEWLOCALS: they run at import time, not as calls.
        v = (f"{mod}.{qual}" if qual else mod, os.path.relpath(code.co_filename, REPO).replace(os.sep, "/"),
             code.co_firstlineno, not qual or not code.co_flags & 0x2)
        _ids[code] = v
    return v


def short(v, n=70):
    try:
        s = repr(v)
    except Exception as e:  # noqa: BLE001
        s = f"<repr failed: {type(e).__name__}>"
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


_NOISE = {"function", "builtin_function_or_method", "method", "module"}


def frame_locals(frame, k=6):
    out = {}
    for name, v in frame.f_locals.items():
        if name.startswith(("__", "@")) or isinstance(v, type) or type(v).__name__ in _NOISE:
            continue
        out[name] = short(v)
        if len(out) >= k:
            break
    return out


def source(fn, lineno):
    return " ".join(linecache.getline(fn, lineno).split())[:160]


def record_failure(test_id, exc):
    frames, site = [], None
    for fr, lineno in traceback.walk_tb(exc.__traceback__):
        code = fr.f_code
        site = f"{code.co_filename}:{lineno}: {source(code.co_filename, lineno)}"
        if not repo_file(code.co_filename):
            continue
        node, path, _, _ = node_of(code)
        frames.append({"node": node, "file": path, "line": lineno, "src": source(code.co_filename, lineno),
                       "frame": fr})
    # Locals only for the innermost few repo frames: that is where the bad value is.
    for f in frames[-3:]:
        f["locals"] = frame_locals(f["frame"])
    for f in frames:
        del f["frame"]
    msg = " ".join(str(exc).split())
    failures.append({"test": test_id, "type": type(exc).__name__, "message": msg[:400], "site": site,
                     "frames": frames})


# ---- function tracking -------------------------------------------------------------------------------
def is_test_file(fn):
    if not repo_file(fn):   # a repro script outside the repo counts as test code; the stdlib and packages don't
        return not fn.startswith("<") and not any(s in fn for s in SKIP_DIRS) and \
            not os.path.realpath(fn).startswith(LIB_PREFIXES)
    p = fn.replace(os.sep, "/")
    base = p.rsplit("/", 1)[-1]
    return (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
            or "/tests/" in p or "/test/" in p)


REPORTING = ("/_pytest/_io/", "/_pytest/assertion/", "/reprlib.py", "/pprint.py")


def start_test(test_id):
    global cur, direct, calls, reporting, all_edges
    cur, direct, calls, reporting, all_edges = {}, set(), {}, False, set()
    tests[test_id] = {"outcome": None, "codes": cur, "direct": direct, "calls": calls, "all_edges": all_edges}
    if MON:
        sys.monitoring.restart_events()


def on_code(code, frame):
    """First run of `code` in this test; `frame` is its caller's frame (None if unknown)."""
    global reporting
    if cur is None or reporting or code in cur or not repo_file(code.co_filename):
        return
    # Walk up through library frames (functools wrappers, pytest internals) to the nearest repo caller.
    caller = None
    for _ in range(8):
        if frame is None:
            break
        fn = frame.f_code.co_filename.replace(os.sep, "/")
        if any(s in fn for s in REPORTING):
            reporting = True   # pytest is formatting the failure: whatever runs now is repr noise
            return
        if repo_file(fn) or is_test_file(fn):
            caller = frame.f_code
            break
        frame = frame.f_back
    cur[code] = len(cur)
    if caller is not None:
        calls[code] = caller
        if is_test_file(caller.co_filename) and not is_test_file(code.co_filename):
            direct.add(code)   # called straight from the test: the API under test


def on_edge(code, frame):
    """Every distinct (nearest repo/test caller, repo callee) pair in the running test (EXECGRAPH_ALL_EDGES=1)."""
    if cur is None or reporting or not repo_file(code.co_filename):
        return
    for _ in range(8):
        if frame is None:
            return
        fn = frame.f_code.co_filename
        if repo_file(fn) or is_test_file(fn):
            all_edges.add((frame.f_code, code))
            return
        frame = frame.f_back


ALL_EDGES = os.environ.get("EXECGRAPH_ALL_EDGES") == "1"   # paper runs: full dynamic call graph, slower
all_edges = set()
MON = hasattr(sys, "monitoring")
if MON:
    mon = sys.monitoring
    TOOL = next(t for t in (mon.PROFILER_ID, 3, 4) if mon.get_tool(t) is None)
    mon.use_tool_id(TOOL, "execgraph")

    def _py_start(code, offset):
        on_code(code, sys._getframe(1).f_back)   # frame 1 is the function being started
        if ALL_EDGES:
            on_edge(code, sys._getframe(1).f_back)
            return None
        return mon.DISABLE

    mon.register_callback(TOOL, mon.events.PY_START, _py_start)
    mon.set_events(TOOL, mon.events.PY_START)
else:
    def _prof(frame, event, arg):
        if event == "call":
            on_code(frame.f_code, frame.f_back)
            if ALL_EDGES:
                on_edge(frame.f_code, frame.f_back)

    sys.setprofile(_prof)
    threading.setprofile(_prof)


def stop_tracing():
    if MON:
        mon.set_events(TOOL, 0)
        mon.free_tool_id(TOOL)
    else:
        sys.setprofile(None)
        threading.setprofile(None)


# ---- runners -----------------------------------------------------------------------------------------
def run_pytest():
    import pytest

    class Plugin:
        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self, item, nextitem):
            start_test(item.nodeid)
            yield

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item, call):
            outcome = yield
            rep = outcome.get_result()
            t = tests.get(item.nodeid)
            if t is None:
                return
            if rep.failed:
                if t["outcome"] != "failed" and call.excinfo is not None:
                    record_failure(item.nodeid, call.excinfo.value)
                t["outcome"] = "failed"
            elif rep.when == "call" and rep.passed and t["outcome"] is None:
                t["outcome"] = "passed"
            elif rep.skipped and t["outcome"] is None:
                t["outcome"] = "skipped"

        @pytest.hookimpl(hookwrapper=True)
        def pytest_collectreport(self, report):
            yield
            if report.failed:   # import/collection errors are failures too
                failures.append({"test": report.nodeid or "<collection>", "type": "CollectionError",
                                 "message": " ".join(str(report.longrepr).split())[-600:], "frames": []})

    # -p no:cacheprovider keeps .pytest_cache out of the repo; -q -x stays off so passing tests give contrast.
    return pytest.main(["-p", "no:cacheprovider", "-q", "--no-header", "-rN", *ARGS], plugins=[Plugin()])


def run_script():
    import runpy
    path = ARGS[0]
    sys.argv = list(ARGS)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    start_test(path)
    try:
        runpy.run_path(path, run_name="__main__")
        tests[path]["outcome"] = "passed"
        return 0
    except SystemExit as e:
        ok = e.code in (None, 0)
        tests[path]["outcome"] = "passed" if ok else "failed"
        if not ok:
            failures.append({"test": path, "type": "SystemExit", "message": str(e.code)[:400], "frames": []})
        return 0 if ok else 1
    except BaseException as e:  # noqa: BLE001
        tests[path]["outcome"] = "failed"
        record_failure(path, e)
        return 1


def main():
    t0 = time.time()
    sys.path.insert(0, REPO)
    try:
        rc = run_pytest() if MODE == "pytest" else run_script()
    finally:
        stop_tracing()
    funcs = {}
    out_tests = {}
    for tid, t in tests.items():
        names = []
        for code, order in sorted(t["codes"].items(), key=lambda kv: kv[1]):
            node, path, line, is_mod = node_of(code)
            funcs.setdefault(node, {"file": path, "line": line, "module_level": is_mod})
            names.append(node)
        out_tests[tid] = {"outcome": t["outcome"] or "unknown", "funcs": list(dict.fromkeys(names)),
                          "direct": sorted({node_of(c)[0] for c in t["direct"]})}
        if t["outcome"] == "failed":   # the dynamic call graph, kept for failing runs only
            out_tests[tid]["calls"] = sorted({(node_of(a)[0], node_of(b)[0]) for b, a in t["calls"].items()
                                              if node_of(a)[0] != node_of(b)[0]})
        if ALL_EDGES:
            out_tests[tid]["edges"] = sorted({(node_of(a)[0], node_of(b)[0]) for a, b in t["all_edges"]
                                              if node_of(a)[0] != node_of(b)[0]})
    with open(OUT, "w") as f:
        json.dump({"exit_code": int(rc), "seconds": round(time.time() - t0, 1), "python": sys.version.split()[0],
                   "tracer": "sys.monitoring" if MON else "sys.setprofile", "tests": out_tests,
                   "funcs": funcs, "failures": failures}, f)
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
