# Spec: Gemma 4 Developer Agent, main leaderboard + paper track

Written 2026-10-30. Where this spec and HARNESS_README.md disagree, the README wins (log it in NOTES.md).

## 1. Facts (checked 2026-10-30)

**Main:** kaggle.com/competitions/gemma-4-developer-agent. Post-train Gemma 4 into an offline coding agent that fixes real Python issues. Scored like SWE-bench (patch applied, hidden tests pass/fail). Score = fraction fixed.

- Submission: `submission.zip` with `agent.yaml` at root (Google ADK Agent Config), optional `prompts/`, `configs/sampling.yaml`, `sub_agents/*.yaml`, `adapters/<name>/` (PEFT LoRA safetensors), `skills/<name>/` (SKILL.md + scripts/ + resources/). No path traversal. Skill scripts run in the persistent Docker sandbox and count against the time budget.
- One base model per submission (all agents/sub-agents): `gemma-4-{31b,12b,e4b,e2b}-it-qat-w4a16-ct`. Different LoRA adapters per agent allowed.
- Tools: run_command, read_file, edit_file, write_file, submit_patch, get_status; get_code_neighbors(node, edge_type?, max_neighbors), search_similar_code(query, k), get_code_subgraph(nodes).
- Budget: 12 h for all tasks incl. sandbox setup, excl. validation. Per-task limits in eval_config.yaml.
- Leaderboard: ~4,137 teams, top public 0.24, 0.02 steps (~50 public tasks). Public = ~50% of test; private decides.
- Prizes $37k/$18k/$10k + $10k Small Model bonus (best E2B/E4B; must be one of 2 final picks).
- Dates (23:59 UTC): rules acceptance + team merge by Nov 25; final submission Dec 2.
- Compute: Kaggle L4x4 (96 GB, no internet, 2× quota rate). Local GPU is 4 GB.

**Paper:** kaggle.com/competitions/gemma-4-developer-agent-paper. Due **Nov 12, 23:59 UTC** (Nov 13, 05:29 IST). Kaggle Writeup ≤3,000 words: title, subtitle, abstract, intro, methods & experiments, related work with citations. Optional public notebook + arXiv-style PDF. Scored 0–5 on novelty, quality (generality), relevance, verifiability, clarity. Prizes: Best Paper $15k, Best New Resource $10k, Best New Application $10k.

## 2. Core idea: ExecGraph

Small agents fail mostly at localisation. The harness ships a static graph but not what actually ran. Run the failing repro/test under a lightweight tracer and overlay onto the static graph: executed functions (hit counts), call path to the exception, arg/return summaries near the failure. Give the agent a small ranked, dynamically confirmed subgraph.

- Main: ExecGraph as a skill (no training needed for first gains) + LoRA so E4B uses it well.
- Paper: empirical study of runtime evidence for small-model localisation/fixing + release ExecGraph (Best Paper + Best New Resource).

## 3. Main leaderboard plan

**A1 (week 1, no training).** Baseline with E4B and 12B: scores, time per task, failure modes.
- `prompts/system.md` order: Reproduce → Localise (ExecGraph + graph tools) → Patch (minimal) → Verify (targeted + nearby tests) → Submit. Never submit without running a test; don't edit tests unless asked.
- `skills/exec_graph/`: `scripts/trace_failure.py <cmd>` (sys.settrace / sys.monitoring, repo modules only, compact JSON: hit counts, exception stack, truncated locals of last N frames); `scripts/rank_suspects.py` (join to graph node IDs; signals: on failing path, Ochiai SBFL when several tests, graph distance to exception site; top-k with reasons); `resources/how_to_use.md`. Guardrails: ~60 s per trace, output cap, fallback to static tools.
- Time policy in `configs/sampling.yaml` + `eval_config.yaml`: per-task cap, margin for sandbox setup.
- Optional: 2–3 candidate patches, pick by most passing tests (measure cost first).
- Exit: E4B+ExecGraph beats E4B without it. Log every submission in EXPERIMENTS.md.

**A2 (weeks 2–3) LoRA.** Teach E4B (opt. 12B) the workflow. Data: own trajectories on training issues (competition split, else permissive SWE-Gym / SWE-bench train — check external-data rules, log licences). Rejection-sample 12B/31B trajectories whose patch passes (if rules allow larger Gemma as teacher). Dedupe vs hidden test repos. PEFT LoRA on E4B QAT base (check adapter loading per README), on L4x4, small runs first, export safetensors in harness format, dry-run load before submitting. Ablations: base / prompt-only / skill / skill+LoRA.

**A3 (by Dec 2).** Two finals: best overall + best E4B/E2B. Prefer consistent configs; don't overfit public 50%.

## 4. Paper plan (due Nov 12)

Working title: "Where did it actually break? Runtime-evidence graphs for small-model software agents" (final title TBD).
- Contributions: ExecGraph library (competition graph format compatible); empirical study on E4B and 12B — localisation hit@k (gold = functions touched by reference patch) and end-to-end fix rate vs static-only and no-graph; analysis of when tracing helps/fails (no repro, import-time failures, flaky tests), time cost, tool-use behaviour.
- Metrics: hit@1/5/10, fix rate, time/task, tool calls/task, share of tasks with a repro. Conditions: none / static / ExecGraph / both; E4B vs 12B (31B if quota). Bootstrap CIs over tasks.
- Deliverables: Writeup <3,000 words, public notebook reproducing localisation, public GitHub repo (MIT/Apache-2.0), optional PDF.
- Fallback: localisation-only study. Ship rather than miss Nov 12.

## 5. Timeline (job starts Nov 2: evenings/weekends)

| Dates | Main | Paper |
|---|---|---|
| Oct 31 – Nov 3 | HARNESS_README, baseline (E4B, 12B), ExecGraph skill v1 | Outline, related work |
| Nov 4 – Nov 9 | ExecGraph on LB; time policy; collect trajectories | Localisation experiments + CIs |
| Nov 10 – Nov 12 | (pause) | Write + submit by Nov 12 23:59 UTC; notebook + repo public |
| Nov 13 – Nov 25 | LoRA SFT on E4B; ablations; accept rules by Nov 25 | — |
| Nov 26 – Dec 2 | Final tuning; 2 finals (one E4B/E2B) | — |

Conflict: PayPal hackathon due Nov 13, 00:30 IST, same night as the paper. Shivansh decides.

## 6. Rules for the repo

Layout per README.md. `make_submission.py` validates the zip. Never commit Kaggle tokens. Check data licence before committing data.

## 7. Open questions for Shivansh

1. Team or solo? (≤5, merge by Nov 25)
2. Kaggle phone verification done? (needed for GPU/L4)
3. Paper vs PayPal on Nov 12–13?
4. Final paper title.
