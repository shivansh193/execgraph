"""E3 hint files from RWG-PPR rankings (v2 parameters, paper/rwg_params_v2.json).

    python notebooks/e3/make_hints.py --e1 experiments/e1/full1/e1

Writes experiments/e3/hints_rwg_F.json (evidence: the task's failing tests, an oracle-test arm) and
hints_rwg_R.json (evidence: nearby existing tests only, the deployable arm pre-registered as `rwg`).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notebooks" / "e1"))
sys.path.insert(0, str(ROOT / "execgraph"))
import analyze  # noqa: E402
from execgraph import rank  # noqa: E402

TOP = 5
TEXT = ("\n\nLocalisation hint (from an automated tool; it can be wrong): the functions most likely involved, "
        "most likely first, as dotted paths `module.Class.function`:\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", type=Path, required=True)
    a = ap.parse_args()
    prm = rank.Params(**json.loads((ROOT / "paper" / "rwg_params_v2.json").read_text()))
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(analyze.DATA / "tasks.jsonl", encoding="utf-8")}
    out = {"F": {}, "R": {}}
    for tid, t in sorted(tasks.items()):
        d = a.e1 / tid
        if not (d / "meta.json").exists():
            continue
        meta = json.loads((d / "meta.json").read_text())
        if not meta.get("graph") or not (analyze.DATA / "graphs" / meta["graph"]).exists():
            continue
        repo = analyze.load_repo(meta, d)
        sem = rank.semantic_edges(repo, prm.sem_k, prm.sem_min)
        evR = analyze.evidence(d, "R")
        for level in ("F", "R"):
            ev = analyze.evidence(d, level)
            if level == "F":
                if ev is None or not ev.n_failed:
                    continue
                ev = rank.with_contrast(ev, evR)   # v2: level-R passing tests as extra contrast
            top = rank.rwg_ppr(repo, t["problem_statement"], ev, prm, sem)[:TOP]
            if top:
                out[level][tid] = TEXT + "".join(f"{i}. `{n}`\n" for i, n in enumerate(top, 1))
    for level, hints in out.items():
        p = ROOT / "experiments" / "e3" / f"hints_rwg_{level}.json"
        p.write_text(json.dumps(hints, indent=1), encoding="utf-8")
        print(p, len(hints))


if __name__ == "__main__":
    main()
