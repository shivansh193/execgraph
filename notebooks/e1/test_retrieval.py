"""E1b (exploratory, written after E1 was scored): can coverage of the existing test suite find a test that runs the
buggy code, before any failing test exists?

    python notebooks/e1/test_retrieval.py          # E1 dir from $E1, full-suite traces from $E1B

Each task's whole existing suite was traced on the buggy code (functions executed per test). With only the issue text,
rank the existing tests and ask whether a top-k test executes a gold function (test-hit@k) and whether it sits in a
file the reference test_patch edits (file-hit@k: where the real regression test was written). Test rankers:

  name       BM25 of the issue over the test id (what level R's pseudo-spectrum uses)
  file_R     tests in the 3 test files nearest the issue by BM25 over file contents (level R's choice), name order
  cov        sum over executed non-test functions f of r(f) * idf(f) / sqrt(#funcs): r = RWG-PPR level S scores
             (issue seeds + static/AST/semantic walk), idf = log(N tests / tests running f)
  cov+name   normalised cov + normalised name

Then localisation with the retrieved tests as pseudo-failing and the rest of the suite as passing contrast
(RWG-PPR v2 params, no failure text): "level R+" next to text, RWG-PPR S and level R as pre-registered.
"""
import gzip
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, "execgraph")
sys.path.insert(0, "notebooks/e1")
import analyze  # noqa: E402
from execgraph import metrics, rank  # noqa: E402
from execgraph.ids import is_test_node  # noqa: E402

E1 = Path(os.environ.get("E1") or "experiments/e1/full1/e1")
E1B = Path(os.environ.get("E1B") or "experiments/e1b/full2/e1")
PREREG = json.load(open("paper/prereg_e1.json"))
prm = rank.Params(**json.load(open("paper/rwg_params_v2.json")))
prm_s = rank.Params(**json.load(open("paper/rwg_params.json")))
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(analyze.DATA / "tasks.jsonl", encoding="utf-8")}
KS = (1, 3, 10)
TOP = 3


def norm(d):
    return rank.normalise({k: v for k, v in d.items() if v > 0})


def iorder(score):
    return [i for i, s in sorted(score.items(), key=lambda kv: (-kv[1], kv[0])) if s > 0]


def test_rankers(full, repo, issue, r_files):
    tests = full["tests"]
    live = [i for i, o in enumerate(full["outcome"]) if o in ("passed", "failed")]
    funcs_of = {i: [] for i in live}
    live_set = set(live)
    for f, idx in full["funcs"].items():
        if is_test_node(f):
            continue
        for i in idx:
            if i in live_set:
                funcs_of[i].append(f)
    n = len(live)
    idf = {f: math.log((n + 1) / (1 + sum(1 for i in idx if i in live_set))) for f, idx in full["funcs"].items()}
    _, r = rank.rwg_ppr(repo, issue, None, prm_s, rank.semantic_edges(repo, prm_s.sem_k, prm_s.sem_min), scores=True)
    r = rank.normalise(r)
    cov = {i: sum(r.get(f, 0) * idf[f] for f in fs) / math.sqrt(len(fs)) for i, fs in funcs_of.items() if fs}
    name = rank.BM25({i: rank.tokens(tests[i].replace("::", " ").replace("/", " ")) for i in live}).scores(
        rank.tokens(issue))
    cn, nn = norm(cov), norm(name)
    hyb = {i: cn.get(i, 0) + nn.get(i, 0) for i in live}
    in_r = [i for i in live if tests[i].split("::")[0] in r_files]
    out = {
        "name": iorder(name),
        "file_R": sorted(in_r, key=lambda i: (-name.get(i, 0), i)),
        "cov": iorder(cov),
        "cov+name": iorder(hyb),
    }
    return out, funcs_of, live


def pseudo_evidence(order, funcs_of, live, top=TOP):
    chosen = set(order[:top])
    ev = rank.Evidence()
    for i in live:
        tgt = ev.failed if i in chosen else ev.passed
        for f in funcs_of[i]:
            tgt[f] = tgt.get(f, 0) + 1
    ev.n_failed = len(chosen)
    return ev


rows = []
LIMIT = int(os.environ.get("LIMIT", "0")) or None
for tdir in sorted(E1B.iterdir())[:LIMIT]:
    tid = tdir.name
    p = tdir / "trace_full.json.gz"
    if not p.exists() or not (E1 / tid / "meta.json").exists():
        continue
    meta = json.loads((E1 / tid / "meta.json").read_text())
    bmeta = json.loads((tdir / "meta.json").read_text())
    repo = analyze.load_repo(meta, E1 / tid)
    gold = set(meta["gold"]["nodes"]) & set(repo.nodes)
    if not gold:
        continue
    try:
        full = json.load(gzip.open(p, "rt", encoding="utf-8"))
    except (OSError, ValueError):
        continue
    issue = tasks[tid]["problem_statement"]
    tp_files = set(bmeta.get("test_files") or meta.get("test_files") or [])
    r_files = set((meta.get("R") or {}).get("files") or [])
    orders, funcs_of, live = test_rankers(full, repo, issue, r_files)
    runs_gold = {i for i in live if gold & set(funcs_of[i])}
    row = {"task": tid, "split": "eval" if tid in PREREG["split"]["eval"] else "tune", "n_tests": len(live),
           "n_gold_tests": len(runs_gold), "any_test_runs_gold": bool(runs_gold),
           "tp_file_exists": any(full["tests"][i].split("::")[0] in tp_files for i in live)}
    for name, o in orders.items():
        for k in KS:
            row[f"{name}:test@{k}"] = float(bool(set(o[:k]) & runs_gold))
            row[f"{name}:file@{k}"] = float(any(full["tests"][i].split("::")[0] in tp_files for i in o[:k]))
    sem = rank.semantic_edges(repo, prm.sem_k, prm.sem_min)
    loc = {"text": rank.rank_text(repo, issue),
           "rwg_S": rank.rwg_ppr(repo, issue, None, prm_s, sem)}
    ev_r = analyze.pseudo_evidence(E1 / tid, issue, prm_s.pseudo_top)
    if ev_r is not None:
        loc["rwg_Rp"] = rank.rwg_ppr(repo, issue, ev_r, prm_s, sem)
    for name in ("name", "cov", "cov+name"):
        loc[f"rwg_R+{name}"] = rank.rwg_ppr(repo, issue, pseudo_evidence(orders[name], funcs_of, live), prm, sem)
    for name, ranking in loc.items():
        for m, v in metrics.task_metrics(ranking, gold).items():
            row[f"loc_{name}:{m}"] = v
    rows.append(row)
    print(tid, row["n_tests"], row["n_gold_tests"], {k: row[k] for k in row if k.endswith("test@3")}, flush=True)


def mean(rs, k):
    v = [r[k] for r in rs if k in r]
    return (round(sum(v) / len(v), 3), len(v)) if v else (None, 0)


for split in ("eval", "all"):
    rs = [r for r in rows if split == "all" or r["split"] == split]
    print(f"\n## split={split}: {len(rs)} tasks; an existing test runs a gold function in "
          f"{sum(r['any_test_runs_gold'] for r in rs)}; a test_patch file already exists in {sum(r['tp_file_exists'] for r in rs)}")
    print("| test ranker | test@1 | test@3 | test@10 | file@1 | file@3 | file@10 |\n|---|---|---|---|---|---|---|")
    print("| random (expected) | " + " | ".join(str(round(sum(1 - (1 - r["n_gold_tests"] / r["n_tests"]) ** k for r in rs)
                                                       / max(len(rs), 1), 3)) for k in KS) + " | | | |")
    for name in ("name", "file_R", "cov", "cov+name"):
        print(f"| {name} | " + " | ".join(str(mean(rs, f"{name}:{x}@{k}")[0]) for x in ("test", "file") for k in KS) + " |")
    print("\n| localisation | n | hit@1 | hit@5 | hit@10 | MRR |\n|---|---|---|---|---|---|")
    names = sorted({k[4:].split(":")[0] for r in rs for k in r if k.startswith("loc_")})
    for name in names:
        print(f"| {name} | {mean(rs, f'loc_{name}:hit@5')[1]} | " +
              " | ".join(str(mean(rs, f"loc_{name}:{m}")[0]) for m in ("hit@1", "hit@5", "hit@10", "mrr")) + " |")
    for a, b, key in (("cov", "name", "{}:test@3"), ("cov+name", "name", "{}:test@3"), ("cov", "file_R", "{}:test@3"),
                      ("cov+name", "name", "{}:file@3"),
                      ("loc_rwg_R+cov+name", "loc_text", "{}:hit@5"), ("loc_rwg_R+cov", "loc_text", "{}:hit@5"),
                      ("loc_rwg_R+cov+name", "loc_rwg_Rp", "{}:hit@5")):
        both = [r for r in rs if key.format(a) in r and key.format(b) in r]
        d, lo, hi, pv = metrics.paired_bootstrap([r[key.format(a)] for r in both], [r[key.format(b)] for r in both])
        if d is not None:
            print(f"{key.format(a)} - {key.format(b)} n={len(both)}: {d:+.3f} [{lo:+.3f},{hi:+.3f}] P<=0 {pv:.3f}")
json.dump(rows, open(os.environ.get("OUT_T", "test_retrieval_rows.json"), "w"), indent=1)
