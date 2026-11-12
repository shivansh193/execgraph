# gemma-dev-agent

Gemma 4 Developer Agent (Kaggle): main leaderboard + paper track.

Idea: **ExecGraph**. Overlay runtime evidence (executed functions, failing call path, value summaries)
on the harness's static code graph, so small Gemma models can localise bugs instead of grepping blindly.

```
submission/    exactly what gets zipped: agent.yaml, prompts/, configs/, skills/, adapters/
execgraph/     the library (pip-installable), tests
experiments/   configs + results (no competition data committed)
notebooks/     Kaggle notebook sources
paper/         writeup draft, figures
data/          downloaded competition data (gitignored)
```

- `NOTES.md`: harness facts and deviations from the spec
- `EXPERIMENTS.md`: every leaderboard submission
- `python make_submission.py`: build and validate `submission.zip`

Kaggle tokens are never committed.

## Paper: "Half the calls are missing" (Gemma 4 Developer Agent paper track)

Paper: `paper/writeup.md` (Markdown) and `paper/latex/` (LaTeX). Every number in it comes from a file here:

| claim | result file | code |
|---|---|---|
| Pre-registration (split, hypotheses H1-H4, E3 arms) | `paper/prereg_e1.json`, `paper/prereg_e3.json` | |
| Frozen ranker parameters (v1, v2) | `paper/rwg_params.json`, `paper/rwg_params_v2.json` | `execgraph/execgraph/rank.py` |
| E1 localisation, D1 missed edges, same-information baselines, level A | `paper/results_e1_eval.md` | `notebooks/e1/` (`e1_main.py`, `e1_task.py`, `analyze.py`, `level_a.py`) |
| v2 ablations | `experiments/remote/v2check/` | `notebooks/e1/v2_ablation.py` |
| Learned ranker (LambdaRank) | `experiments/e1/ltr_F/summary.md` | `notebooks/e1/ltr.py` |
| E1b test retrieval | `paper/results_e1b.md` | `notebooks/e1/test_retrieval.py` |
| E3 agent hint study | `paper/results_e3.md`, `experiments/e3/` | `notebooks/e3/score.py` |
| SWE-bench Verified replication | `paper/results_swebench.md` | `notebooks/swebench/` |

Tracer: `submission/skills/exec-graph/scripts/_tracer.py` (stdlib only). Missed-edge causes: `execgraph/execgraph/edge_causes.py`.

The competition data (tasks, graphs, embeddings) is not included: it may only be shared with competition participants.
Attach the competition to a Kaggle notebook (`notebooks/e1/build.py`, `notebooks/remote/build.py` build them) to
regenerate the traces and every E1 number. Agent run logs are omitted for the same reason.
