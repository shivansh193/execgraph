"""Level A: localisation from the reproduction tests the E4B agent wrote itself (exploratory).

    python notebooks/e1/level_a.py        # E1 dir from $E1, agent-repro traces from $E1A

Each agent repro is one instance (several per task). Reports: did the repro fail on the buggy code (a real
reproduction), and, for repros that did, hit@k of RWG-PPR v2 with the repro's trace (plus level-R contrast) next to
text alone and RWG-PPR v2 with the task's real failing tests (level F, oracle) on the same tasks.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "execgraph")
sys.path.insert(0, "notebooks/e1")
import analyze  # noqa: E402
from execgraph import metrics, rank  # noqa: E402

E1 = Path(os.environ.get("E1") or "experiments/e1/full1/e1")
E1A = Path(os.environ.get("E1A") or "experiments/e1a/run1/e1")
prm = rank.Params(**json.load(open("paper/rwg_params_v2.json")))
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(analyze.DATA / "tasks.jsonl", encoding="utf-8")}

status, rows = Counter(), []
for tdir in sorted(E1A.iterdir()):
    tid = tdir.name
    if not (E1 / tid / "meta.json").exists():
        continue
    meta = json.loads((E1 / tid / "meta.json").read_text())
    repo = analyze.load_repo(meta, E1 / tid)
    gold = set(meta["gold"]["nodes"]) & set(repo.nodes)
    evR, evF = analyze.evidence(E1 / tid, "R"), analyze.evidence(E1 / tid, "F")
    issue = tasks[tid]["problem_statement"]
    sem = rank.semantic_edges(repo, prm.sem_k, prm.sem_min)
    for p in sorted(tdir.glob("trace_A*.json")):
        try:
            evA = rank.Evidence.from_trace(json.loads(p.read_text()))
        except ValueError:
            status["unreadable"] += 1
            continue
        collection = "CollectionError" in evA.failure_text
        if not evA.n_failed:
            status["collection_error" if collection else "no_failing_test"] += 1
            continue
        status["repro_fails"] += 1
        if not gold:
            status["no_gold_in_graph"] += 1
            continue
        row = {"task": tid, "repro": p.name,
               "A": metrics.task_metrics(rank.rwg_ppr(repo, issue, rank.with_contrast(evA, evR), prm, sem), gold),
               "text": metrics.task_metrics(rank.rank_text(repo, issue), gold),
               "A_no_failure_seeds": metrics.task_metrics(rank.rwg_ppr(
                   repo, issue, rank.with_contrast(evA, evR), rank.Params(**{**vars(prm), "w_fail": 0.0}), sem), gold),
               "gold_ran_in_repro": bool(gold & set(evA.failed))}
        if evF is not None and evF.n_failed:
            row["F"] = metrics.task_metrics(rank.rwg_ppr(repo, issue, rank.with_contrast(evF, evR), prm, sem), gold)
        rows.append(row)

print("repro outcomes on buggy code:", dict(status))
print(f"scored repros: {len(rows)} over {len({r['task'] for r in rows})} tasks; "
      f"gold function executed by the agent's failing repro: {sum(r['gold_ran_in_repro'] for r in rows)}/{len(rows)}")
for name in ("text", "A_no_failure_seeds", "A"):
    print(name, {m: round(sum(r[name][m] for r in rows) / max(len(rows), 1), 3) for m in ("hit@1", "hit@5", "hit@10", "mrr")})
withF = [r for r in rows if "F" in r]
for name in ("text", "A", "F"):
    print(f"[{len(withF)} repros whose task also has F] {name}",
          {m: round(sum(r[name][m] for r in withF) / max(len(withF), 1), 3) for m in ("hit@1", "hit@5", "mrr")})
for a, b in (("A", "text"), ("F", "A")):
    both = [r for r in rows if a in r and b in r]
    d, lo, hi, pv = metrics.paired_bootstrap([r[a]["hit@5"] for r in both], [r[b]["hit@5"] for r in both])
    if d is not None:
        print(f"{a} - {b} hit@5 n={len(both)}: {d:+.3f} [{lo:+.3f},{hi:+.3f}] P<=0 {pv:.3f}")
json.dump(rows, open(os.environ.get("OUT_A", "level_a_rows.json"), "w"), indent=1)
