split=eval params={"w_static": 1.0, "w_ast": 1.0, "w_runtime": 3.0, "w_sem": 2.0, "sem_k": 5, "sem_min": 0.5, "reverse": 0.3, "alpha": 0.3, "mix": 0.3, "exact_bonus": 1.0, "spectrum": true, "iters": 50, "pseudo_top": 3}

tasks: 89, scored: 79, statuses: {'ok': 79, 'no_gold_in_graph': 10}

| ranker | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| bm25 | 79 | 0.177 [0.09,0.27] | 0.367 [0.27,0.48] | 0.506 [0.39,0.62] | 0.286 [0.21,0.37] |
| crash_F | 70 | 0.114 [0.04,0.20] | 0.114 [0.04,0.20] | 0.114 [0.04,0.20] | 0.114 [0.04,0.20] |
| embedding | 79 | 0.013 [0.00,0.04] | 0.089 [0.03,0.15] | 0.114 [0.05,0.19] | 0.062 [0.03,0.10] |
| khop | 79 | 0.177 [0.09,0.27] | 0.392 [0.29,0.51] | 0.519 [0.41,0.63] | 0.288 [0.21,0.37] |
| ochiai_F | 70 | 0.086 [0.03,0.16] | 0.300 [0.20,0.41] | 0.414 [0.30,0.53] | 0.197 [0.14,0.27] |
| ochiai_Rp | 79 | 0.076 [0.03,0.14] | 0.215 [0.13,0.30] | 0.253 [0.16,0.35] | 0.143 [0.09,0.21] |
| prfl_F | 70 | 0.171 [0.09,0.26] | 0.371 [0.27,0.49] | 0.557 [0.44,0.67] | 0.290 [0.21,0.37] |
| random | 79 | 0.000 [0.00,0.00] | 0.025 [0.00,0.06] | 0.038 [0.00,0.09] | 0.017 [0.01,0.03] |
| rwg_F | 70 | 0.371 [0.26,0.49] | 0.643 [0.53,0.76] | 0.757 [0.66,0.86] | 0.499 [0.41,0.60] |
| rwg_F_notext | 70 | 0.129 [0.06,0.21] | 0.414 [0.30,0.54] | 0.529 [0.41,0.64] | 0.258 [0.19,0.34] |
| rwg_R | 79 | 0.139 [0.06,0.23] | 0.367 [0.27,0.48] | 0.443 [0.33,0.56] | 0.255 [0.18,0.34] |
| rwg_R_noruntime | 79 | 0.139 [0.06,0.23] | 0.367 [0.27,0.48] | 0.443 [0.33,0.56] | 0.251 [0.18,0.33] |
| rwg_Rp | 79 | 0.215 [0.13,0.30] | 0.481 [0.37,0.59] | 0.595 [0.48,0.70] | 0.329 [0.25,0.41] |
| rwg_S | 79 | 0.165 [0.08,0.25] | 0.405 [0.30,0.52] | 0.468 [0.35,0.58] | 0.278 [0.20,0.36] |
| rwg_S_nosem | 79 | 0.165 [0.08,0.25] | 0.405 [0.30,0.52] | 0.506 [0.39,0.62] | 0.276 [0.20,0.36] |
| testdirect_F | 70 | 0.071 [0.01,0.14] | 0.243 [0.14,0.36] | 0.286 [0.19,0.40] | 0.146 [0.08,0.22] |
| text | 79 | 0.177 [0.09,0.27] | 0.405 [0.30,0.52] | 0.506 [0.39,0.62] | 0.297 [0.22,0.38] |

| test | n | diff hit@5 | 95% CI | P(diff<=0) |
|---|---|---|---|---|
| H1: rwg_R vs text | 79 | -0.038 | [-0.101,+0.013] | 0.962 |
| H2: rwg_R vs rwg_S | 79 | -0.038 | [-0.089,+0.000] | 1.000 |
| H3a: rwg_F vs ochiai_F | 70 | +0.343 | [+0.229,+0.471] | 0.000 |
| H3b: rwg_F vs prfl_F | 70 | +0.271 | [+0.143,+0.414] | 0.000 |
| H4: rwg_S vs text | 79 | +0.000 | [-0.038,+0.038] | 0.682 |

crash->gold hops (F): n=15, 0: 8, 1: 1, 2: 2, 3: 3, 5: 1
## Paired (eval, tasks with a failing-test trace)

| comparison | n | hit@5 diff | 95% CI | MRR diff | 95% CI |
|---|---|---|---|---|---|
| rwg_F vs text | 70 | +0.214 | [+0.100, +0.329] | +0.190 | [+0.102, +0.282] |
| rwg_F vs rwg_F without text seeds | 70 | +0.229 | [+0.086, +0.371] | +0.241 | [+0.142, +0.344] |
| rwg_F vs bm25 | 70 | +0.271 | [+0.143, +0.414] | +0.214 | [+0.111, +0.317] |
| rwg_Rp vs text (secondary, not pre-registered) | 79 | +0.076 | [-0.038, +0.190] | +0.032 | [-0.041, +0.096] |

By repo (rwg_F vs text, hit@5): fastapi 0.60 vs 0.31 (n=35), rich 0.68 vs 0.46 (n=28), requests 0.83 vs 0.83 (n=6), httpx 0 vs 1 (n=1).

## D1: executed call edges vs static graphs (all 129 tasks, R+F traces, repo->repo, both ends in the competition graph)

42,024 distinct executed edges. In the competition graph: 23.2%. In the AST graph (precise kinds): 49.1%. In either: 50.3%.
Causes for the 20,871 edges missed by both: property/descriptor 29.0%, dunder protocol 26.6%, attribute call on an
unknown receiver 26.0%, implicit constructor 6.0%, unresolved name 3.8%, via library code 2.5%, callback reference 2.0%,
decorator wrapper 2.0%, callback parameter 1.2%, inheritance dispatch 0.6%, reflection 0.1%, runtime import 0.1%.
(2,894 further edges have an endpoint the competition graph has no node for.)

## Same-information baselines (added after the eval split was scored; they test the baselines, not our tuning)

Issue text + failing-test spectrum for every row, eval split, n=70:

| ranker | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| RWG-PPR (F) | 0.371 | 0.643 | 0.757 | 0.499 |
| RWG-PPR (F), walk off (seed = text x (1 + 2 Ochiai)) | 0.386 | 0.629 | 0.743 | 0.506 |
| RWG-PPR (F), no runtime edges | 0.386 | 0.629 | 0.757 | 0.499 |
| text + PRFL (w=1) | 0.329 | 0.643 | 0.757 | 0.474 |
| text + PRFL (w=2) | 0.257 | 0.657 | 0.757 | 0.420 |
| text + Ochiai (w=1) | 0.329 | 0.571 | 0.700 | 0.454 |

**Finding: with the same information, the graph walk and the runtime edges add nothing measurable.** The whole gain over
spectrum methods comes from adding the issue text to the failing-test spectrum; a plain weighted sum of text and PRFL
scores matches RWG-PPR on hit@5. Reason: a failing test executes a gold function in 60 of 72 eval tasks (83%; 68% of
gold functions on average), so the spectrum already contains the answer and the walk has little to add.

## Level A: the reproduction tests E4B wrote itself (exploratory)

53 repros written with `write_file` by the E4B ExecGraph agent in dev runs v2-v5 (32 tasks), each traced alone on the
buggy code in the scorer environment (kernel gda-e1a-agent).

- On the buggy code: 26 fail (a real reproduction, 49%), 20 pass (the repro does not reproduce the bug), 7 do not
  collect (import errors in the agent's test).
- Of the 24 failing repros with gold in the graph (20 tasks), the agent's repro executes a gold function in 12.
- RWG-PPR v2 with the agent's repro (+ level-R contrast) vs text on the same 24: hit@5 0.708 vs 0.583
  (+0.125 [+0.000, +0.292], P<=0 0.037); without failure seeds 0.667. hit@1 unchanged (0.458).
- On the 21 of those whose task also has the real failing tests: text 0.667, agent repro 0.810, real tests (F) 0.952
  hit@5.
- Selection: tasks where E4B wrote a failing repro are easier for text too (0.58 here vs 0.41 on all eval tasks).
