"""Score every E1 ranker on every task (paper/prereg_e1.json).

    python notebooks/e1/analyze.py --e1 experiments/e1/<run>/e1 --split tune   # tuning (grid with --grid)
    python notebooks/e1/analyze.py --e1 ... --split eval --params paper/rwg_params.json

Inputs: E1 kernel outputs (per-task meta.json, trace_R.json, trace_F.json, ast_edges.json, runtime_edges.json),
data/raw/graphs, data/raw/embeddings, data/raw/tasks.jsonl. Writes <out>/per_task.csv and <out>/summary.md.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "execgraph"))
from execgraph import metrics, rank  # noqa: E402
from execgraph.ids import is_test_node  # noqa: E402
from execgraph.static_ast import PRECISE  # noqa: E402

DATA = Path(os.environ.get("EG_DATA", ROOT / "data" / "raw"))   # Kaggle: the competition input dir
PREREG = json.loads((ROOT / "paper" / "prereg_e1.json").read_text())


def load_repo(meta, task_dir):
    gpath = DATA / "graphs" / meta["graph"]
    g = json.loads(gpath.read_text(encoding="utf-8"))
    nodes = [n["id"] for n in g["nodes"]]
    epath = DATA / "embeddings" / meta["graph"].replace(".json", ".npz")
    emb = None
    if epath.exists():
        z = np.load(epath)
        dim = next(iter(z[k] for k in z.files)).shape[0]
        emb = np.stack([z[n] if n in z.files else np.zeros(dim, np.float32) for n in nodes])
    ast_edges = []
    p = task_dir / "ast_edges.json"
    if p.exists():
        ast_edges = [(s, d) for s, d, k in json.loads(p.read_text()) if k in PRECISE]
    return rank.Repo(nodes, {n["id"]: n.get("text", "") for n in g["nodes"]},
                     [(e["source"], e["target"]) for e in g["edges"]], ast_edges, emb)


def evidence(task_dir, name):
    p = task_dir / f"trace_{name}.json"
    try:
        return rank.Evidence.from_trace(json.loads(p.read_text())) if p.exists() else None
    except ValueError:
        return None


def pseudo_evidence(task_dir, issue, top):
    p = task_dir / "trace_R.json"
    try:
        return rank.pseudo_spectrum(json.loads(p.read_text()), issue, top) if p.exists() else None
    except ValueError:
        return None


def crash_distance(repo, ev, gold):
    """Undirected hops from the innermost crash frame to the nearest gold node (static + ast + runtime)."""
    if not ev or not ev.crash_frames:
        return None
    adj = {}
    for a, b in list(repo.static_edges) + list(repo.ast_edges) + list(ev.runtime_edges):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    start = [n for n in reversed(ev.crash_frames) if not is_test_node(n)]
    if not start:
        return None
    seen, q = {start[0]: 0}, deque([start[0]])
    while q:
        n = q.popleft()
        if n in gold:
            return seen[n]
        for m in adj.get(n, ()):
            if m not in seen:
                seen[m] = seen[n] + 1
                q.append(m)
    return None


def rankers(repo, issue, evR, evF, prm, sem, evRp=None):
    out = {"random": rank.rank_random(repo), "bm25": rank.rank_bm25(repo, issue),
           "text": rank.rank_text(repo, issue, prm.exact_bonus), "embedding": rank.rank_embedding(repo, issue),
           "khop": rank.rank_khop(repo, issue), "rwg_S": rank.rwg_ppr(repo, issue, None, prm, sem),
           "rwg_S_nosem": rank.rwg_ppr(repo, issue, None, prm, [])}
    if evR is not None:
        out["rwg_R"] = rank.rwg_ppr(repo, issue, evR, prm, sem)
        out["rwg_R_noruntime"] = rank.rwg_ppr(repo, issue, rank.Evidence(
            failed=evR.failed, passed=evR.passed, n_failed=evR.n_failed), prm, sem)
    if evRp is not None:
        out["rwg_Rp"] = rank.rwg_ppr(repo, issue, evRp, prm, sem)
        out["ochiai_Rp"] = rank.rank_ochiai(evRp)
    if evF is not None and evF.n_failed:
        out.update({"crash_F": rank.rank_crash(evF), "ochiai_F": rank.rank_ochiai(evF),
                    "prfl_F": rank.rank_prfl(repo, evF), "testdirect_F": rank.rank_test_files(repo, evF),
                    "rwg_F": rank.rwg_ppr(repo, issue, evF, prm, sem),
                    "rwg_F_notext": rank.rwg_ppr(repo, "", evF, prm, sem)})
        # same-information baselines (issue + failing tests), added after the eval split was scored
        och, prfl = rank.ochiai(evF), rank.prfl_scores(repo, evF)
        for w in (0.5, 1.0, 2.0):
            out[f"text+ochiai_w{w}"] = rank.rank_fused(repo, issue, och, w, prm.exact_bonus)
            out[f"text+prfl_w{w}"] = rank.rank_fused(repo, issue, prfl, w, prm.exact_bonus)
        out["rwg_F_nowalk"] = rank.rwg_ppr(repo, issue, evF, rank.Params(**{**vars(prm), "mix": 0.0}), sem)
        out["rwg_F_noruntime"] = rank.rwg_ppr(repo, issue, rank.Evidence(
            failed=evF.failed, passed=evF.passed, n_failed=evF.n_failed), prm, sem)
    return out


def score_tasks(e1, ids, prm, tasks, cache, only=None):
    rows = []
    for tid in ids:
        d = e1 / tid
        mp = d / "meta.json"
        if not mp.exists():
            rows.append({"instance_id": tid, "status": "no_meta"})
            continue
        meta = json.loads(mp.read_text())
        if not meta.get("graph") or "gold" not in meta:
            rows.append({"instance_id": tid, "status": "no_graph_or_gold"})
            continue
        if not (DATA / "graphs" / meta["graph"]).exists():
            rows.append({"instance_id": tid, "status": "graph_not_downloaded"})
            continue
        if tid not in cache:
            repo = load_repo(meta, d)
            cache[tid] = (repo, evidence(d, "R"), evidence(d, "F"), {})
        repo, evR, evF, semc = cache[tid]
        pkey = ("Rp", prm.pseudo_top)
        if pkey not in semc:
            semc[pkey] = pseudo_evidence(d, tasks[tid]["problem_statement"], prm.pseudo_top)
        key = (prm.sem_k, prm.sem_min)
        if key not in semc:
            semc[key] = rank.semantic_edges(repo, prm.sem_k, prm.sem_min)
        nodes = set(repo.nodes)
        gold = set(meta["gold"]["nodes"]) & nodes
        base = {"instance_id": tid, "repo": tid.split("_")[0], "n_gold": len(gold),
                "gold_total": len(meta["gold"]["nodes"]), "module_level": bool(meta["gold"]["module_level"]),
                "new_only": bool(meta["gold"]["new_only"]),
                "R_ok": evR is not None, "F_ok": evF is not None,
                "F_failed": evF.n_failed if evF else 0}
        if not gold:
            rows.append({**base, "status": "no_gold_in_graph"})
            continue
        base["status"] = "ok"
        base["crash_dist"] = crash_distance(repo, evF, gold)
        if only:
            ev = {"rwg_F": evF if evF is not None and evF.n_failed else None, "rwg_R": evR, "rwg_Rp": semc[pkey],
                  "rwg_S": None}[only]
            if only != "rwg_S" and ev is None:
                rows.append({**base, "status": "no_evidence"})
                continue
            ranked = {only: rank.rwg_ppr(repo, tasks[tid]["problem_statement"], ev, prm, semc[key])}
        else:
            ranked = rankers(repo, tasks[tid]["problem_statement"], evR, evF, prm, semc[key], semc[pkey])
        for name, r in ranked.items():
            for m, v in metrics.task_metrics(r, gold).items():
                base[f"{name}:{m}"] = v
        rows.append(base)
    return rows


def summarise(rows, metric="hit@5"):
    ok = [r for r in rows if r.get("status") == "ok"]
    names = sorted({k.split(":")[0] for r in ok for k in r if ":" in k})
    lines = [f"tasks: {len(rows)}, scored: {len(ok)}, statuses: {dict(Counter(r.get('status') for r in rows))}", "",
             "| ranker | n | hit@1 | hit@5 | hit@10 | MRR |", "|---|---|---|---|---|---|"]
    for n in names:
        cells = []
        for m in ("hit@1", "hit@5", "hit@10", "mrr"):
            vals = [r.get(f"{n}:{m}") for r in ok if f"{n}:{m}" in r]
            mean, lo, hi = metrics.bootstrap(vals)
            cells.append(f"{mean:.3f} [{lo:.2f},{hi:.2f}]" if mean is not None else "-")
        lines.append(f"| {n} | {sum(1 for r in ok if f'{n}:{metric}' in r)} | " + " | ".join(cells) + " |")
    pairs = [("rwg_R", "text", "H1"), ("rwg_R", "rwg_S", "H2"), ("rwg_F", "ochiai_F", "H3a"),
             ("rwg_F", "prfl_F", "H3b"), ("rwg_S", "text", "H4")]
    lines += ["", "| test | n | diff hit@5 | 95% CI | P(diff<=0) |", "|---|---|---|---|---|"]
    for a, b, h in pairs:
        both = [r for r in ok if f"{a}:{metric}" in r and f"{b}:{metric}" in r]
        d, lo, hi, p = metrics.paired_bootstrap([r[f"{a}:{metric}"] for r in both], [r[f"{b}:{metric}"] for r in both])
        if d is not None:
            lines.append(f"| {h}: {a} vs {b} | {len(both)} | {d:+.3f} | [{lo:+.3f},{hi:+.3f}] | {p:.3f} |")
    cd = [r["crash_dist"] for r in ok if r.get("crash_dist") is not None]
    if cd:
        lines += ["", f"crash->gold hops (F): n={len(cd)}, " + ", ".join(f"{k}: {v}" for k, v in sorted(Counter(cd).items()))]
    return "\n".join(lines)


GRID = {"w_runtime": [1.0, 3.0, 10.0], "w_sem": [0.0, 0.5, 2.0], "reverse": [0.3, 0.7, 1.0],
        "alpha": [0.15, 0.3, 0.5], "mix": [0.3, 0.5, 0.8], "exact_bonus": [0.5, 1.0, 2.0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", type=Path, required=True)
    ap.add_argument("--split", choices=["tune", "eval", "all"], default="tune")
    ap.add_argument("--params", type=Path)
    ap.add_argument("--grid", action="store_true", help="coordinate search on the tune split")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(DATA / "tasks.jsonl", encoding="utf-8")}
    ids = sorted(tasks) if a.split == "all" else PREREG["split"][a.split]
    if a.grid and a.split != "tune":
        sys.exit("grid search is only allowed on the tune split (prereg)")
    prm = rank.Params(**json.loads(a.params.read_text())) if a.params else rank.Params()
    out = a.out or ROOT / "experiments" / "e1" / f"analysis_{a.split}"
    out.mkdir(parents=True, exist_ok=True)
    cache = {}
    if a.grid:
        target = os.environ.get("E1_TUNE_TARGET", "rwg_R")

        def obj(p):
            rows = [r for r in score_tasks(a.e1, ids, p, tasks, cache, only=target) if r.get("status") == "ok"]
            vals = [r.get(f"{target}:mrr", 0) for r in rows]
            return sum(vals) / max(len(vals), 1)

        best, best_v, log = prm, obj(prm), []
        for _ in range(2):                       # two coordinate-descent sweeps
            for k, vs in GRID.items():
                for v in vs:
                    p = rank.Params(**{**vars(best), k: v})
                    val = obj(p)
                    log.append({**vars(p), "obj": val})
                    if val > best_v + 1e-9:
                        best, best_v = p, val
            print("sweep best", round(best_v, 4), vars(best), flush=True)
        (out / "grid_log.json").write_text(json.dumps(log, indent=1))
        (out / "best_params.json").write_text(json.dumps(vars(best), indent=1))
        prm = best
    rows = score_tasks(a.e1, ids, prm, tasks, cache)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (":" in k, k))
    with open(out / "per_task.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    s = f"split={a.split} params={json.dumps(vars(prm))}\n\n" + summarise(rows)
    (out / "summary.md").write_text(s)
    print(s)


if __name__ == "__main__":
    main()
