"""E1 per-task work, independent of the Kaggle harness so it can be tested locally.

`run(cmd, timeout)` executes a shell command in the task sandbox (cwd = workspace) and returns
(exit_code, stdout). Paths below are host paths; the tracer and outputs live outside the workspace.
"""
import json
import os
import shlex
import time

from execgraph import edge_causes, static_ast
from execgraph.gold import gold_from_patch
from execgraph.ids import is_test_node, is_test_path
from execgraph.rank import BM25, tokens

PYTEST_FLAGS = '-p no:anyio -o timeout=0 -o python_classes="Test* *Test"'
R_FILES = 3


def pick_nearby_tests(ws, issue, exclude=(), k=R_FILES):
    """Existing test files most similar to the issue text (BM25 over path + contents): what an agent with no
    failing test could run. Never looks at the task's test_patch."""
    docs = {}
    for rel, path in static_ast.iter_py(ws):
        base = os.path.basename(rel)
        if not is_test_path(rel) or base == "conftest.py" or rel in exclude:
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()[:60000]
        except OSError:
            continue
        docs[rel] = tokens(rel) * 3 + tokens(text)
    scores = BM25(docs).scores(tokens(issue)) if docs else {}
    return [p for p, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def trace(run, tracer, out, files, timeout, extra=""):
    t0 = time.time()
    cmd = (f"EXECGRAPH_ALL_EDGES=1 PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s {shlex.quote(str(tracer))} "
           f"{shlex.quote(str(out))} {shlex.quote(str(run.workspace))} pytest {' '.join(map(shlex.quote, files))} "
           f"{PYTEST_FLAGS} {extra}")
    code, stdout = run(cmd, timeout)
    ok = os.path.exists(out)
    return {"files": files, "exit": code, "seconds": round(time.time() - t0, 1), "ok": ok,
            "tail": (stdout or "")[-1500:]}


def level_s_and_r(run, ws, task, tracer, outdir):
    """Before test_patch: gold labels, the AST graph, and a trace of nearby existing tests."""
    meta = {"instance_id": task["instance_id"], "repo": task["repo"]}
    t0 = time.time()

    def read_old(p):
        f = os.path.join(ws, p)
        return open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else None

    g = gold_from_patch(task["patch"], read_old)
    meta["gold"] = {k: sorted(v) for k, v in vars(g).items()}
    sg = static_ast.build(ws)
    meta["ast_seconds"] = round(time.time() - t0, 1)
    json.dump([[s, d, k] for (s, d), k in sg.edges.items()], open(os.path.join(outdir, "ast_edges.json"), "w"))
    files = pick_nearby_tests(ws, task["problem_statement"])
    meta["R"] = trace(run, tracer, os.path.join(outdir, "trace_R.json"), files, 600) if files else {"files": []}
    return meta, sg


def level_agent(run, ws, repros, tracer, outdir):
    """Level A: trace the reproduction tests the E4B agent itself wrote in earlier dev runs, on the buggy code.
    Each goes under tests/ (so the repo's conftest applies), is traced alone, then removed."""
    out = []
    for i, r in enumerate(repros):
        rel = f"tests/test_zz_agent_repro_{i}.py"
        path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(r["content"])
        try:
            res = trace(run, tracer, os.path.join(outdir, f"trace_A{i}.json"), [rel], 300)
        finally:
            os.remove(path)
        res.update(run=r.get("run"), original_path=r.get("path"))
        out.append(res)
    return out


def level_full(run, ws, tracer, outdir, timeout=1800):
    """E1b: the whole existing test suite on the buggy code (before test_patch), functions per test only (the
    tracer's fast default mode). Saved as a gzipped inverted index: tests, outcomes, function -> test indices."""
    import gzip
    raw = os.path.join(outdir, "trace_full_raw.json")
    t0 = time.time()
    cmd = (f"PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s {shlex.quote(str(tracer))} {shlex.quote(raw)} "
           f"{shlex.quote(str(run.workspace))} pytest --continue-on-collection-errors {PYTEST_FLAGS} tests")
    code, stdout = run(cmd, timeout)
    meta = {"exit": code, "seconds": round(time.time() - t0, 1), "ok": os.path.exists(raw),
            "tail": (stdout or "")[-1000:]}
    if meta["ok"]:
        t = json.load(open(raw))
        ids = sorted(t.get("tests", {}))
        idx = {tid: i for i, tid in enumerate(ids)}
        inv = {}
        for tid, v in t["tests"].items():
            for f in v.get("funcs", []):
                inv.setdefault(f, []).append(idx[tid])
        out = {"tests": ids, "outcome": [t["tests"][i]["outcome"] for i in ids],
               "direct": {i: t["tests"][tid].get("direct", []) for tid, i in idx.items() if t["tests"][tid].get("direct")},
               "funcs": inv, "failures": t.get("failures", [])[:50]}
        with gzip.open(os.path.join(outdir, "trace_full.json.gz"), "wt", encoding="utf-8") as f:
            json.dump(out, f)
        os.remove(raw)
        meta.update(n_tests=len(ids), n_funcs=len(inv),
                    outcomes={o: out["outcome"].count(o) for o in set(out["outcome"])})
    return meta


def runtime_edges(path):
    if not os.path.exists(path):
        return set()
    t = json.load(open(path))
    return {tuple(e) for v in t.get("tests", {}).values() for e in v.get("edges") or v.get("calls") or []}


def missed_edges(sg, comp_graph, outdir):
    """Runtime edges (R and F) between repo functions, checked against both static graphs, with causes."""
    comp_nodes = {n["id"] for n in comp_graph["nodes"]}
    comp_edges = {(e["source"], e["target"]) for e in comp_graph["edges"]}
    ast_precise = sg.precise_edges()
    ast_any = set(sg.edges)
    rows = []
    rt = runtime_edges(os.path.join(outdir, "trace_R.json")) | runtime_edges(os.path.join(outdir, "trace_F.json"))
    for a, b in sorted(rt):
        if is_test_node(a) or is_test_node(b):
            continue
        rows.append({
            "src": a, "dst": b,
            "in_comp_nodes": a in comp_nodes and b in comp_nodes,
            "in_comp": (a, b) in comp_edges or (b, a) in comp_edges,
            "in_ast": (a, b) in ast_precise,
            "in_ast_any": (a, b) in ast_any,
            "ast_kind": sg.edges.get((a, b)),
            "cause": None if (a, b) in ast_precise else edge_causes.classify(sg, a, b),
        })
    json.dump(rows, open(os.path.join(outdir, "runtime_edges.json"), "w"))
    return rows


def f_command(cmd, tracer, out):
    """Rewrite the scorer's pytest command to run the same tests under the tracer. A test file that fails to
    import (a feature task's new symbol) must not stop the other test files from running."""
    new = cmd.replace("python3 -s -m pytest ",
                      f"EXECGRAPH_ALL_EDGES=1 python3 -s {shlex.quote(str(tracer))} {shlex.quote(str(out))} /workspace pytest "
                      "--continue-on-collection-errors ", 1)
    return new if new != cmd else None
