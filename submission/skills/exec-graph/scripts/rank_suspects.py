"""Rank suspect functions from an ExecGraph trace and print a compact report (fits the 5,000-char tool cap).

    rank_suspects.py [--trace /tmp/execgraph/trace.json] [--top 10]

Signals per non-test function run by a failing test:
  - Ochiai spectrum score: ef / sqrt(failed * (ef + ep)), ef/ep = failing/passing tests that ran it;
  - distance to the exception site along the failing traceback (innermost repo frame = 0);
  - called directly by the failing test, or named in the failure message (the API under test);
  - how late it first ran in the failing test (weak; only matters when no test passed).
Names are competition graph node ids, so they can go straight to get_code_neighbors / get_code_subgraph.
"""
import json
import math
import os
import sys
import tempfile

OUT_DIR = os.path.join(tempfile.gettempdir(), "execgraph")   # /tmp/execgraph in the task container
TRACE = os.path.join(OUT_DIR, "trace.json")
MAX_CHARS = 4400
API_BONUS = {0: 0.3, 1: 0.15, 2: 0.07}   # by hops from a function the failing test calls directly


def is_test(path):
    parts = path.split("/")
    base = parts[-1]
    return (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
            or any(p in ("tests", "test", "testing") for p in parts[:-1]))


def outcome_sets(trace):
    failed = [t for t, v in trace["tests"].items() if v["outcome"] == "failed"]
    passed = [t for t, v in trace["tests"].items() if v["outcome"] == "passed"]
    return failed, passed


def tb_distance(trace):
    """node -> smallest distance from the exception site over all failures (source frames only)."""
    dist = {}
    for f in trace["failures"]:
        src = [fr for fr in f["frames"] if not is_test(fr["file"])]
        for d, fr in enumerate(reversed(src)):
            dist[fr["node"]] = min(d, dist.get(fr["node"], d))
    return dist


def rank(trace, top=10):
    failed, passed = outcome_sets(trace)
    funcs, tests = trace["funcs"], trace["tests"]
    dist = tb_distance(trace)
    ef, ep, late, direct = {}, {}, {}, set()
    text = " ".join(f"{f['message']} {f.get('site') or ''}" for f in trace["failures"])
    callees = {}
    for t in failed:
        direct.update(tests[t].get("direct", []))
        for a, b in tests[t].get("calls", []):
            callees.setdefault(a, set()).add(b)
        names = tests[t]["funcs"]
        for i, n in enumerate(names):
            ef[n] = ef.get(n, 0) + 1
            late[n] = max(late.get(n, 0.0), (i + 1) / len(names))
    for t in passed:
        for n in tests[t]["funcs"]:
            ep[n] = ep.get(n, 0) + 1
    # Hops from the API under test along the failing run's call edges (the dynamic call graph).
    api_hops, frontier = {n: 0 for n in direct}, list(direct)
    while frontier:
        nxt = []
        for a in frontier:
            for b in callees.get(a, ()):
                if b not in api_hops:
                    api_hops[b] = api_hops[a] + 1
                    nxt.append(b)
        frontier = nxt
    w_late = 0.05 if passed else 0.15
    out = []
    for n in set(ef) | set(dist):
        meta = funcs.get(n, {})
        if is_test(meta.get("file", "")) or (meta.get("module_level") and n not in dist):
            continue
        a, b = ef.get(n, 0), ep.get(n, 0)
        ochiai = a / math.sqrt(len(failed) * (a + b)) if failed and a else 0.0
        d = dist.get(n)
        named = n.rsplit(".", 1)[-1] + "(" in text
        hops = 0 if named else api_hops.get(n)
        score = (ochiai + (0.6 / (1 + d) if d is not None else 0.0) + API_BONUS.get(hops, 0.0)
                 + w_late * late.get(n, 0.0))
        why = [f"ran in {a}/{len(failed)} failing, {b}/{len(passed)} passing"]
        if named:
            why.append("named in the failure")
        elif hops == 0:
            why.append("called directly by the failing test")
        elif hops is not None and hops in API_BONUS:
            why.append(f"called by the API under test ({hops} hop{'s' if hops > 1 else ''})")
        if d is not None:
            why.insert(0, "raised here" if d == 0 else f"on failing path ({d} frames above raise)")
        out.append({"node": n, "file": meta.get("file", "?"), "line": meta.get("line", 0),
                    "score": round(score, 3), "why": "; ".join(why)})
    out.sort(key=lambda s: (-s["score"], s["node"]))
    return out[:top]


def render(trace, suspects, cmd=""):
    failed, passed = outcome_sets(trace)
    lines = [f"ExecGraph: `{cmd}` -> {len(failed)} failed, {len(passed)} passed, exit {trace['exit_code']}, "
             f"{trace['seconds']}s ({trace['tracer']}, python {trace['python']})"]
    if not failed and not trace["failures"]:
        lines.append("NOTHING FAILED: the bug did not reproduce. Fix the repro (assert the expected behaviour) "
                     "and run this again before editing code.")
        return "\n".join(lines)
    for f in trace["failures"][:2]:
        lines.append(f"\nFAILURE {f['test']}\n  {f['type']}: {f['message'][:300]}")
        if f.get("site"):
            lines.append(f"  raised at {f['site']}")
        frames = f["frames"][-8:]
        if frames:
            lines.append("  repo frames, outermost -> innermost:")
        for fr in frames:
            lines.append(f"    {fr['file']}:{fr['line']}  {fr['node']}  | {fr.get('src', '')[:100]}")
            if fr.get("locals"):
                loc = ", ".join(f"{k}={v}" for k, v in fr["locals"].items())
                lines.append(f"      locals: {loc[:260]}")
    if len(trace["failures"]) > 2:
        lines.append(f"\n(+{len(trace['failures']) - 2} more failures in the trace file)")
    if suspects:
        lines.append("\nSUSPECTS (graph node ids; read the code, or get_code_neighbors on them):")
        for i, s in enumerate(suspects, 1):
            lines.append(f"{i:>2}. {s['node']}  {s['file']}:{s['line']}  score {s['score']}\n      {s['why']}")
    if not passed and failed:
        lines.append("\nTip: no test passed, so ranking leans on the traceback. Add the existing test file for this "
                     "area to the same call (passing tests sharpen the ranking).")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 20] + "\n...[truncated]"


def main(argv):
    path, top = TRACE, 10
    it = iter(argv)
    for a in it:
        if a == "--trace":
            path = next(it)
        elif a == "--top":
            top = int(next(it))
    if not os.path.exists(path):
        print(f"No trace at {path}. Run trace_failure.py first.")
        return 1
    with open(path) as f:
        trace = json.load(f)
    print(render(trace, rank(trace, top), trace.get("cmd", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
