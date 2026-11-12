"""E3 paired comparison: hint arms vs no hint, per model (exact McNemar on discordant tasks).

    python notebooks/e3/score.py            # reads experiments/e3/<model>-<arm>/dev_eval_*.csv
"""
import csv
import glob
from math import comb
from pathlib import Path

ROOT = Path("experiments/e3")


def load(d):
    f = glob.glob(str(d / "dev_eval_*.csv"))
    return {r["instance_id"]: r for r in csv.DictReader(open(f[0]))} if f else None


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


runs = {d.name: load(d) for d in sorted(ROOT.iterdir()) if d.is_dir() and load(d)}
print("| run | solved | with patch | median tool calls | errors |")
print("|---|---|---|---|---|")
for name, r in runs.items():
    v = list(r.values())
    print(f"| {name} | {sum(x['resolved'] == 'True' for x in v)}/{len(v)} | {sum(x['has_patch'] == 'True' for x in v)} "
          f"| {median([int(x['tool_calls'] or 0) for x in v])} | {sum(bool(x['error']) for x in v)} |")
print("\n| model | arm vs none | solved | discordant (hint only : none only) | exact McNemar p | gained | lost |")
print("|---|---|---|---|---|---|---|")
for name, r in runs.items():
    model, arm = name.split("-", 1)
    base = runs.get(f"{model}-none")
    if arm == "none" or base is None:
        continue
    ids = sorted(set(r) & set(base))
    gained = [i for i in ids if r[i]["resolved"] == "True" and base[i]["resolved"] != "True"]
    lost = [i for i in ids if r[i]["resolved"] != "True" and base[i]["resolved"] == "True"]
    s = sum(r[i]["resolved"] == "True" for i in ids)
    s0 = sum(base[i]["resolved"] == "True" for i in ids)
    print(f"| {model} | {arm} | {s} vs {s0} /{len(ids)} | {len(gained)}:{len(lost)} | {mcnemar(len(gained), len(lost)):.3f} "
          f"| {', '.join(gained)} | {', '.join(lost)} |")
