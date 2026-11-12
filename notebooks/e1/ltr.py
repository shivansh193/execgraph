"""Learned localisation (LambdaMART over execgraph.features) with cross-validation and group ablations.

    python notebooks/e1/ltr.py --e1 experiments/e1/full1/e1 --level F     # tasks with a failing-test trace
    python notebooks/e1/ltr.py --e1 experiments/e1/full1/e1 --level R     # every task, nearby passing tests only

Exploratory (not in the E1 pre-registration): reported as 5-fold cross-validation over tasks (folds by task, fixed
seed), plus train-on-tune / test-on-eval for comparison with the pre-registered split.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "execgraph"))
sys.path.insert(0, str(ROOT / "notebooks" / "e1"))
import analyze  # noqa: E402
from execgraph import features, metrics, rank  # noqa: E402

MAIN = {"fastapi": "fastapi", "rich": "rich", "requests": "requests", "httpx": "httpx"}


def build(e1, level, prm, cache_path):
    if cache_path.exists():
        return pickle.loads(cache_path.read_bytes())
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(analyze.DATA / "tasks.jsonl", encoding="utf-8")}
    data = {}
    for tid in sorted(tasks):
        d = e1 / tid
        if not (d / "meta.json").exists():
            continue
        meta = json.loads((d / "meta.json").read_text())
        if not meta.get("graph") or not (analyze.DATA / "graphs" / meta["graph"]).exists():
            continue
        repo = analyze.load_repo(meta, d)
        gold = set(meta["gold"]["nodes"]) & set(repo.nodes)
        if not gold:
            continue
        evR, evF = analyze.evidence(d, "R"), analyze.evidence(d, "F")
        if level == "F":
            if evF is None or not evF.n_failed:
                continue
            ev = rank.with_contrast(evF, evR)
        else:
            ev = evR
        sem = rank.semantic_edges(repo, prm.sem_k, prm.sem_min)
        issue = tasks[tid]["problem_statement"]
        rows = features.task_features(repo, issue, ev, prm, sem, MAIN[tid.split("_")[0]])
        base = {"rwg": rank.rwg_ppr(repo, issue, ev, prm, sem), "text": rank.rank_text(repo, issue)}
        if level == "F":
            base["text+prfl"] = rank.rank_fused(repo, issue, rank.prfl_scores(repo, evF), 1.0)
            base["rwg_frozen"] = rank.rwg_ppr(repo, issue, evF, rank.Params(**{**vars(prm), "w_fail": 0.0}), sem)
        data[tid] = {"rows": rows, "gold": gold, "base": base}
        print(tid, len(rows), "cands; gold in cands:", sum(r["node"] in gold for r in rows), flush=True)
    cache_path.write_bytes(pickle.dumps(data))
    return data


def matrix(data, ids, feats):
    X, y, groups = [], [], []
    for tid in ids:
        rows = data[tid]["rows"]
        X += [[r[f] for f in feats] for r in rows]
        y += [int(r["node"] in data[tid]["gold"]) for r in rows]
        groups.append(len(rows))
    return np.array(X, dtype=float), np.array(y), groups


def fit(data, ids, feats, seed=0):
    X, y, g = matrix(data, ids, feats)
    m = lgb.LGBMRanker(objective="lambdarank", n_estimators=200, learning_rate=0.05, num_leaves=15,
                       min_child_samples=10, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                       random_state=seed, verbose=-1)
    m.fit(X, y, group=g)
    return m


def score(m, data, ids, feats):
    out = {}
    for tid in ids:
        rows = data[tid]["rows"]
        p = m.predict(np.array([[r[f] for f in feats] for r in rows], dtype=float))
        ranking = [rows[i]["node"] for i in np.argsort(-p, kind="stable")]
        out[tid] = metrics.task_metrics(ranking, data[tid]["gold"])
    return out


def cv(data, feats, folds=5, seed=0):
    ids = sorted(data)
    rng = np.random.RandomState(seed)
    order = list(rng.permutation(ids))
    res = {}
    for k in range(folds):
        test = order[k::folds]
        train = [t for t in ids if t not in test]
        res.update(score(fit(data, train, feats, seed), data, test, feats))
    return res


def table(name, res):
    vals = list(res.values())
    cells = []
    for m in ("hit@1", "hit@5", "hit@10", "mrr"):
        mean, lo, hi = metrics.bootstrap([v[m] for v in vals])
        cells.append(f"{mean:.3f} [{lo:.2f},{hi:.2f}]")
    return f"| {name} | {len(vals)} | " + " | ".join(cells) + " |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", type=Path, required=True)
    ap.add_argument("--level", choices=["F", "R"], default="F")
    a = ap.parse_args()
    prm = rank.Params(**{**json.loads((ROOT / "paper" / "rwg_params.json").read_text()), "w_fail": 1.0})
    out = ROOT / "experiments" / "e1" / f"ltr_{a.level}"
    out.mkdir(parents=True, exist_ok=True)
    data = build(a.e1, a.level, prm, out / "features.pkl")
    pre = json.loads((ROOT / "paper" / "prereg_e1.json").read_text())["split"]
    ids = sorted(data)
    lines = [f"level {a.level}: {len(ids)} tasks, {sum(len(d['rows']) for d in data.values())} candidates; "
             f"gold reachable in candidates for {sum(any(r['node'] in d['gold'] for r in d['rows']) for d in data.values())}",
             "", "| ranker (5-fold CV over tasks) | n | hit@1 | hit@5 | hit@10 | MRR |", "|---|---|---|---|---|---|"]
    for b in data[ids[0]]["base"]:
        lines.append(table(f"{b} (no learning)", {t: metrics.task_metrics(data[t]["base"][b], data[t]["gold"]) for t in ids}))
    full = cv(data, features.FEATURES)
    lines.append(table("LTR all features", full))
    ab = {}
    for gname, gf in features.GROUPS.items():
        ab[gname] = cv(data, [f for f in features.FEATURES if f not in gf])
        lines.append(table(f"LTR without {gname}", ab[gname]))
    lines += ["", "| paired vs LTR all (hit@5, CV) | diff | 95% CI | P(diff<=0) |", "|---|---|---|---|"]
    for b in data[ids[0]]["base"]:
        bres = {t: metrics.task_metrics(data[t]["base"][b], data[t]["gold"]) for t in ids}
        d, lo, hi, p = metrics.paired_bootstrap([full[t]["hit@5"] for t in ids], [bres[t]["hit@5"] for t in ids])
        lines.append(f"| LTR all - {b} | {d:+.3f} | [{lo:+.3f},{hi:+.3f}] | {p:.3f} |")
    for gname, r in ab.items():
        d, lo, hi, p = metrics.paired_bootstrap([full[t]["hit@5"] for t in ids], [r[t]["hit@5"] for t in ids])
        lines.append(f"| LTR all - LTR without {gname} | {d:+.3f} | [{lo:+.3f},{hi:+.3f}] | {p:.3f} |")
    tr = [t for t in ids if t in pre["tune"]]
    te = [t for t in ids if t in pre["eval"]]
    m = fit(data, tr, features.FEATURES)
    lines += ["", f"train on tune ({len(tr)}), test on eval ({len(te)}):",
              "| ranker | n | hit@1 | hit@5 | hit@10 | MRR |", "|---|---|---|---|---|---|",
              table("LTR all features", score(m, data, te, features.FEATURES))]
    for b in data[ids[0]]["base"]:
        lines.append(table(f"{b} (no learning)", {t: metrics.task_metrics(data[t]["base"][b], data[t]["gold"]) for t in te}))
    imp = sorted(zip(features.FEATURES, fit(data, ids, features.FEATURES).feature_importances_), key=lambda x: -x[1])
    lines += ["", "feature importance (split counts, all tasks): " + ", ".join(f"{f} {int(v)}" for f, v in imp)]
    s = "\n".join(lines)
    (out / "summary.md").write_text(s)
    print(s)


if __name__ == "__main__":
    main()
