"""Score the SWE-bench Verified generality check with the frozen E1 parameters (no tuning on these tasks).

    python3 score.py --out out --tasks verified.jsonl

Rankers as in E1: text, BM25, Ochiai/PRFL (failing tests), RWG-PPR v1 (paper/rwg_params.json) at S, R and F,
RWG-PPR v2 (paper/rwg_params_v2.json) at F with level-R contrast, and the same-information baselines without a graph.
No competition graph or embeddings exist here: the graph is our AST graph (all edge kinds as "static", precise kinds as
"ast", class -> method containment). Also D1: executed edges vs the AST graph, with causes.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "execgraph"))
from execgraph import metrics, rank  # noqa: E402
from execgraph.static_ast import PRECISE  # noqa: E402

V1 = rank.Params(**json.load(open(ROOT / "paper/rwg_params.json")))
V2 = rank.Params(**json.load(open(ROOT / "paper/rwg_params_v2.json")))


def load_ev(p):
    try:
        return rank.Evidence.from_trace(json.loads(p.read_text())) if p.exists() else None
    except ValueError:
        return None


def score(td, task):
    meta = json.loads((td / "meta.json").read_text())
    if meta.get("error") or not (td / "repo.json").exists():
        return {"status": "error"}, meta
    rp = json.loads((td / "repo.json").read_text())
    repo = rank.Repo(rp["nodes"], rp["text"], [tuple(e) for e in rp["static_edges"]],
                     [(s, d) for s, d, k in rp["ast_edges"] if k in PRECISE], None)
    gold = set(meta["gold"]["nodes"]) & set(repo.nodes)
    if not gold:
        return {"status": "no_gold_in_graph"}, meta
    issue = task["problem_statement"]
    evR, evF = load_ev(td / "trace_R.json"), load_ev(td / "trace_F.json")
    out = {"status": "ok", "repo": task["repo"], "hasF": bool(evF and evF.n_failed)}
    r = {"text": rank.rank_text(repo, issue), "bm25": rank.rank_bm25(repo, issue),
         "rwg_S": rank.rwg_ppr(repo, issue, None, V1, [])}
    rawR = json.loads((td / "trace_R.json").read_text()) if (td / "trace_R.json").exists() else None
    if rawR:
        try:
            r["rwg_Rp"] = rank.rwg_ppr(repo, issue, rank.pseudo_spectrum(rawR, issue, V1.pseudo_top), V1, [])
        except ValueError:
            pass
    if out["hasF"]:
        evC = rank.with_contrast(evF, evR)
        r["ochiai_F"] = rank.rank_ochiai(evF)
        r["prfl_F"] = rank.rank_prfl(repo, evF)
        r["rwg_F_v1"] = rank.rwg_ppr(repo, issue, evF, V1, [])
        r["text+prfl_F"] = rank.rank_fused(repo, issue, rank.prfl_scores(repo, evF), 1.0)
        r["rwg_F_v2"] = rank.rwg_ppr(repo, issue, evC, V2, [])
        r["rwg_F_v2_nowalk"] = rank.rwg_ppr(repo, issue, evC, rank.Params(**{**vars(V2), "mix": 0.0}), [])
        t, fs = rank.normalise(rank.text_seeds(repo, issue)), rank.normalise(rank.failure_seeds(repo, evC))
        pr = rank.normalise(rank.prfl_scores(repo, evC))
        r["text+failure+prfl_F"] = rank.order({n: t.get(n, 0) + fs.get(n, 0) + pr.get(n, 0) for n in set(t) | set(fs) | set(pr)})
        out["gold_executed_by_failing"] = bool(gold & set(evF.failed))
    for k, v in r.items():
        for m, x in metrics.task_metrics(v, gold).items():
            out[f"{k}:{m}"] = x
    return out, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--tasks", default="verified.jsonl")
    a = ap.parse_args()
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(a.tasks)}
    rows, status, d1, causes, per_repo = [], Counter(), Counter(), Counter(), defaultdict(Counter)
    for td in sorted(Path(a.out).iterdir()):
        if not (td / "meta.json").exists():
            continue
        row, meta = score(td, tasks[td.name])
        status[row["status"]] += 1
        row["task"] = td.name
        rows.append(row)
        p = td / "runtime_edges.json"
        if p.exists():
            for s, d, inp, ina, cause in json.loads(p.read_text()):
                d1["edges"] += 1
                d1["in_ast_precise"] += inp
                d1["in_ast_any"] += ina
                per_repo[meta["repo"]]["edges"] += 1
                per_repo[meta["repo"]]["in_ast_precise"] += inp
                if not ina:
                    causes[cause] += 1
        print(td.name, row["status"], flush=True)
    ok = [r for r in rows if r["status"] == "ok"]
    F = [r for r in ok if r["hasF"]]
    print(f"\n# SWE-bench Verified (pytest repos): {len(rows)} tasks, {dict(status)}, with failing trace {len(F)}")
    print(f"repos: {dict(Counter(r['repo'] for r in ok))}")
    print("gold executed by a failing test:", sum(r.get("gold_executed_by_failing", False) for r in F), "/", len(F))
    print("\n| ranker | n | hit@1 | hit@5 | hit@10 | MRR |\n|---|---|---|---|---|---|")
    names = sorted({k.split(":")[0] for r in ok for k in r if ":" in k})
    summ = {}
    for nm in names:
        sub = F if any(x in nm for x in ("_F", "F_")) else ok
        vals = {m: [r[f"{nm}:{m}"] for r in sub if f"{nm}:{m}" in r] for m in ("hit@1", "hit@5", "hit@10", "mrr")}
        summ[nm] = vals
        cells = []
        for m in ("hit@1", "hit@5", "hit@10", "mrr"):
            mu, lo, hi = metrics.bootstrap(vals[m])
            cells.append("-" if mu is None else f"{mu:.3f} [{lo:.2f},{hi:.2f}]")
        print(f"| {nm} | {len(vals['hit@5'])} | " + " | ".join(cells) + " |")
    print("\n| paired (tasks with a failing trace) | n | hit@5 diff | 95% CI | P(diff<=0) |\n|---|---|---|---|---|")
    for x, y in (("rwg_F_v1", "text"), ("rwg_F_v1", "ochiai_F"), ("rwg_F_v1", "prfl_F"), ("rwg_F_v1", "text+prfl_F"),
                 ("rwg_F_v2", "rwg_F_v1"), ("rwg_F_v2", "text+failure+prfl_F"), ("rwg_F_v2", "rwg_F_v2_nowalk"),
                 ("rwg_S", "text"), ("rwg_Rp", "text")):
        both = [r for r in (F if "_F" in x or "_F" in y else ok) if f"{x}:hit@5" in r and f"{y}:hit@5" in r]
        d, lo, hi, pv = metrics.paired_bootstrap([r[f"{x}:hit@5"] for r in both], [r[f"{y}:hit@5"] for r in both])
        if d is not None:
            print(f"| {x} vs {y} | {len(both)} | {d:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {pv:.3f} |")
    if d1["edges"]:
        print(f"\nD1: {d1['edges']} executed repo->repo edges between AST-graph nodes; in AST precise "
              f"{d1['in_ast_precise'] / d1['edges']:.1%}, in AST any kind {d1['in_ast_any'] / d1['edges']:.1%}")
        tot = sum(causes.values())
        print("missed causes:", {k: f"{v / tot:.1%}" for k, v in causes.most_common()})
        print("per repo precise:", {k: f"{v['in_ast_precise'] / max(v['edges'], 1):.1%} of {v['edges']}" for k, v in per_repo.items()})
    json.dump(rows, open("swebench_rows.json", "w"), indent=1)


if __name__ == "__main__":
    main()
