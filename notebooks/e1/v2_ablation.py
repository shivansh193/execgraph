"""v2 ablations and same-information fusions (usage: python notebooks/e1/v2_ablation.py tune|eval). E1 dir from $E1."""
import json, os, sys
sys.path.insert(0,"execgraph"); sys.path.insert(0,"notebooks/e1")
import analyze
from execgraph import rank, metrics
from pathlib import Path
base=json.load(open("paper/rwg_params.json")); v2={**base,"w_fail":1.0}
P=json.load(open("paper/prereg_e1.json")); D=Path(os.environ.get("E1") or "experiments/e1/full1/e1")
tasks={json.loads(l)["instance_id"]:json.loads(l) for l in open(analyze.DATA/"tasks.jsonl",encoding="utf-8")}
split=sys.argv[1]
R={}
def add(name,tid,r,g): R.setdefault(name,{})[tid]=metrics.task_metrics(r,g)
for tid in P["split"][split]:
    m=json.load(open(D/tid/"meta.json")); repo=analyze.load_repo(m,D/tid); g=set(m["gold"]["nodes"])&set(repo.nodes)
    evF=analyze.evidence(D/tid,"F"); evR=analyze.evidence(D/tid,"R")
    if not g or evF is None or not evF.n_failed: continue
    ev=rank.with_contrast(evF,evR); sem=rank.semantic_edges(repo); issue=tasks[tid]["problem_statement"]
    add("v2 (walk)",tid,rank.rwg_ppr(repo,issue,ev,rank.Params(**v2),sem),g)
    add("v2 no walk (mix=0)",tid,rank.rwg_ppr(repo,issue,ev,rank.Params(**{**v2,"mix":0.0}),sem),g)
    add("v2 no runtime edges",tid,rank.rwg_ppr(repo,issue,rank.Evidence(failed=ev.failed,passed=ev.passed,n_failed=ev.n_failed,failure_text=ev.failure_text),rank.Params(**v2),sem),g)
    add("v2 no semantic edges",tid,rank.rwg_ppr(repo,issue,ev,rank.Params(**v2),[]),g)
    add("v2 no contrast",tid,rank.rwg_ppr(repo,issue,evF,rank.Params(**v2),sem),g)
    add("v2 no failure seeds",tid,rank.rwg_ppr(repo,issue,ev,rank.Params(**base),sem),g)
    fs=rank.failure_seeds(repo,ev); t=rank.normalise(rank.text_seeds(repo,issue)); pr=rank.normalise(rank.prfl_scores(repo,ev)); fsn=rank.normalise(fs)
    add("text+failure+prfl (same info, no graph)",tid,rank.order({n:t.get(n,0)+fsn.get(n,0)+pr.get(n,0) for n in set(t)|set(fsn)|set(pr)}),g)
    och=rank.normalise(rank.ochiai(ev))
    add("text+failure+ochiai (same info, no graph)",tid,rank.order({n:t.get(n,0)+fsn.get(n,0)+och.get(n,0) for n in set(t)|set(fsn)|set(och)}),g)
    add("v1 frozen",tid,rank.rwg_ppr(repo,issue,evF,rank.Params(**base),sem),g)
for k,v in R.items():
    vals=list(v.values()); print(f"{k:45s} n={len(vals)}", {m: round(sum(x[m] for x in vals)/len(vals),3) for m in ("hit@1","hit@5","hit@10","mrr")})
ids=sorted(R["v2 (walk)"])
for other in [k for k in R if k!="v2 (walk)"]:
    d,lo,hi,p=metrics.paired_bootstrap([R["v2 (walk)"][t]["hit@5"] for t in ids],[R[other][t]["hit@5"] for t in ids])
    d2,lo2,hi2,p2=metrics.paired_bootstrap([R["v2 (walk)"][t]["mrr"] for t in ids],[R[other][t]["mrr"] for t in ids])
    print(f"v2 - {other:42s} hit@5 {d:+.3f} [{lo:+.3f},{hi:+.3f}] p={p:.3f} | mrr {d2:+.3f} [{lo2:+.3f},{hi2:+.3f}]")
