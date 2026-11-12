"""Generality check on SWE-bench Verified: the E1 trace protocol inside the official per-task Docker images.

    python3 run.py --out /work/out [--repos ...] [--limit N] [--jobs 6]

Runs on a Linux VM with Docker (no GPU). Per task, mirroring notebooks/e1/e1_task.py:
  1. start swebench/sweb.eval.x86_64.<id> and copy /testbed out (buggy code, before test_patch);
  2. on the host: gold functions from the reference patch, the AST graph (all edges + precise kinds), node source;
  3. level R: trace the 3 existing test files nearest the issue by BM25, on the buggy code;
  4. level F: apply test_patch and trace the FAIL_TO_PASS tests (the task's real failing tests);
  5. remove the container and image.
Writes <out>/<id>/{meta.json, repo.json, trace_R.json, trace_F.json}. Only pytest repos (FAIL_TO_PASS are pytest ids).
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "execgraph"))
sys.path.insert(0, str(HERE.parent / "e1"))
from execgraph import static_ast  # noqa: E402
from execgraph.gold import gold_from_patch  # noqa: E402
from e1_task import pick_nearby_tests, runtime_edges  # noqa: E402
from execgraph import edge_causes  # noqa: E402
from execgraph.ids import is_test_node  # noqa: E402

TRACER = HERE.parent.parent / "submission/skills/exec-graph/scripts/_tracer.py"
PYTEST_REPOS = {"astropy/astropy", "matplotlib/matplotlib", "pytest-dev/pytest", "scikit-learn/scikit-learn",
                "sphinx-doc/sphinx", "pydata/xarray", "pylint-dev/pylint", "psf/requests", "pallets/flask",
                "mwaskom/seaborn"}
ACT = "source /opt/miniconda3/bin/activate && conda activate testbed && cd /testbed"


def sh(cmd, timeout=None):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT {timeout}s " + str(e.stdout or "")[-2000:]


def images(iid):
    """Epoch AI's public GHCR mirror of the SWE-bench images first (no anonymous Docker Hub pull limit), then Docker Hub."""
    return ["ghcr.io/epoch-research/swe-bench.eval.x86_64." + iid + ":latest",
            "swebench/sweb.eval.x86_64." + iid.replace("__", "_1776_").lower() + ":latest"]


def repo_payload(sg, root):
    """Nodes (defs), node source (first 4000 chars) and edges, for execgraph.rank.Repo."""
    text, lines = {}, {}
    for d in sg.defs.values():
        m = sg.modules[d.module]
        if m.path not in lines:
            try:
                lines[m.path] = open(os.path.join(root, m.path), encoding="utf-8", errors="replace").read().split("\n")
            except OSError:
                lines[m.path] = []
        n = d.node
        text[d.id] = "\n".join(lines[m.path][n.lineno - 1:getattr(n, "end_lineno", n.lineno)])[:4000]
    contain = [(d.cls, d.id) for d in sg.defs.values() if d.cls]
    return {"nodes": sorted(sg.defs), "text": text,
            "static_edges": [[s, t] for (s, t) in sg.edges] + [[a, b] for a, b in contain],
            "ast_edges": [[s, t, k] for (s, t), k in sg.edges.items()]}


def d1(sg, od):
    """D1: executed repo->repo call edges (R and F) against the AST graph, with causes for the missed ones."""
    precise, anyk, nodes = sg.precise_edges(), set(sg.edges), set(sg.defs)
    rows = []
    rt = runtime_edges(str(od / "trace_R.json")) | runtime_edges(str(od / "trace_F.json"))
    for a, b in sorted(rt):
        if is_test_node(a) or is_test_node(b) or a not in nodes or b not in nodes:
            continue
        rows.append([a, b, (a, b) in precise, (a, b) in anyk,
                     None if (a, b) in precise else edge_causes.classify(sg, a, b)])
    json.dump(rows, open(od / "runtime_edges.json", "w"))


def trace(cname, out, tests, timeout):
    t0 = time.time()
    cmd = (f"{ACT} && EXECGRAPH_ALL_EDGES=1 timeout {timeout} python /tmp/_tracer.py /tmp/out.json /testbed pytest "
           f"-p no:cacheprovider {' '.join(map(shlex.quote, tests))}")
    code, so = sh(f"docker exec {cname} bash -lc {shlex.quote(cmd)}", timeout + 60)
    ok = sh(f"docker cp {cname}:/tmp/out.json {shlex.quote(str(out))}")[0] == 0
    sh(f"docker exec {cname} rm -f /tmp/out.json")
    return {"tests": tests, "exit": code, "ok": ok, "seconds": round(time.time() - t0, 1), "tail": so[-1500:]}


def run_task(task, out_root):
    iid = task["instance_id"]
    od = Path(out_root) / iid
    if (od / "meta.json").exists():
        return iid, "cached"
    od.mkdir(parents=True, exist_ok=True)
    cname = "eg_" + iid.replace("__", "_").replace("-", "_")
    meta = {"instance_id": iid, "repo": task["repo"]}
    tmp = Path(tempfile.mkdtemp(prefix="eg_"))
    t0 = time.time()
    try:
        img = None
        for cand in images(iid):
            code, so = sh(f"docker pull -q {cand}", 1800)
            if code == 0:
                img = cand
                break
        if img is None:
            meta["error"] = "pull: " + so[-500:]
            return iid, meta["error"]
        meta["image"] = img
        sh(f"docker rm -f {cname}")
        code, so = sh(f"docker run -d --name {cname} {img} sleep infinity", 300)
        if code:
            meta["error"] = "run: " + so[-500:]
            return iid, meta["error"]
        sh(f"docker cp {shlex.quote(str(TRACER))} {cname}:/tmp/_tracer.py")
        sh(f"docker cp {cname}:/testbed {shlex.quote(str(tmp))}/testbed", 900)
        ws = str(tmp / "testbed")
        meta["python"] = sh(f"docker exec {cname} bash -lc {shlex.quote(ACT + ' && python -V')}")[1].strip()[-40:]

        def read_old(p):
            f = os.path.join(ws, p)
            return open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else None

        g = gold_from_patch(task["patch"], read_old)
        meta["gold"] = {k: sorted(v) for k, v in vars(g).items()}
        sg = static_ast.build(ws)
        json.dump(repo_payload(sg, ws), open(od / "repo.json", "w"))
        files = pick_nearby_tests(ws, task["problem_statement"])
        meta["R"] = trace(cname, od / "trace_R.json", files, 600) if files else {"tests": []}
        with open(tmp / "test.patch", "w") as f:
            f.write(task["test_patch"])
        sh(f"docker cp {tmp}/test.patch {cname}:/tmp/test.patch")
        code, so = sh(f"docker exec {cname} bash -lc {shlex.quote(ACT + ' && git apply -v /tmp/test.patch')}", 120)
        meta["test_patch_applied"] = code == 0
        f2p = json.loads(task["FAIL_TO_PASS"]) if isinstance(task["FAIL_TO_PASS"], str) else list(task["FAIL_TO_PASS"])
        meta["F"] = trace(cname, od / "trace_F.json", f2p, 900) if code == 0 else None
        d1(sg, od)
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"{type(e).__name__}: {e}"
    finally:
        meta["seconds"] = round(time.time() - t0, 1)
        json.dump(meta, open(od / "meta.json", "w"), indent=1)
        sh(f"docker rm -f {cname}")
        for cand in images(iid):
            sh(f"docker rmi -f {cand}")
        shutil.rmtree(tmp, ignore_errors=True)
    return iid, meta.get("error") or f"ok {meta['seconds']}s R={bool(meta.get('R', {}).get('ok'))} F={bool((meta.get('F') or {}).get('ok'))}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="verified.jsonl")
    ap.add_argument("--out", default="out")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    tasks = [json.loads(l) for l in open(a.tasks)]
    tasks = [t for t in tasks if t["repo"] in PYTEST_REPOS and (not a.only or t["instance_id"] in a.only)]
    tasks = tasks[:a.limit] if a.limit else tasks
    print(f"{len(tasks)} tasks", flush=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for iid, status in ex.map(lambda t: run_task(t, a.out), tasks):
            print(time.strftime("%H:%M:%S"), iid, status, flush=True)


if __name__ == "__main__":
    main()
