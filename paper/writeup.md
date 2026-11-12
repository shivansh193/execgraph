# Half the calls are missing: runtime call graphs, test evidence and bug localisation for small coding agents

*Subtitle: Static code graphs miss half the calls that execute. A failing test fused with the issue text localises the bug; for Gemma 4 31B, a correct location does not change the fix rate.*

## Abstract

The Gemma 4 Developer Agent competition ships each repository with a static code graph so that agents built on small
models can find where a bug lives. We measure what that graph misses and what runtime evidence adds. Tracing the tests of 129 tasks in the scorer's own environment, we find that the competition graph
contains 23% of the 42,024 repo-to-repo call edges that execute, and an independent AST analysis with name resolution
49%. The missing half is properties, dunder protocols and calls on receivers of unknown type. We then rank functions with
a personalised PageRank walk over static, AST, runtime and embedding edges, seeded by the issue text and the failing
test (RWG-PPR). In a pre-registered evaluation (40 tuning / 89 held-out tasks), with the task's failing tests RWG-PPR
puts an edited function in its top 5 for 64% of held-out tasks, against 41% for issue text, 37% for PRFL and 30% for
Ochiai. A same-information ablation shows the gain comes from fusing issue text with the failing-test spectrum, not
from the walk; a revised ranker that also reads the failure's own text reaches 77%, and a learned ranker loses 6 points
when its graph features are removed. Without a failing test, nothing beats issue text. The E4B agent's own
reproduction tests fail on the buggy code only 49% of the time, but when they do, localisation improves from 58% to
71%. Ranking the existing tests by what they execute finds one that runs the buggy function in the top 3 for 80% of
tasks (66% by test name), a template for that reproduction. Finally, giving Gemma 4 31B a correct location in the prompt
did not change its fix rate (12 of 32 tasks either way): for a capable agent, localisation is not the bottleneck. On
192 SWE-bench Verified tasks from 10 further repositories, with parameters frozen, every localisation finding
replicates.

## 1. Introduction

The competition gives every agent a static code graph to find where a bug lives, and public notebooks report that
graph tools rarely return anything useful. We ask why, what would, and whether a better location helps an agent.

Spectrum-based fault localisation (Ochiai; PRFL, which runs PageRank over the
executed call graph) uses test coverage but ignores the issue. LLM localisation over static graphs (LocAgent, CoSIL,
OrcaLoca, Agentless) uses the issue and a static graph but no execution. Runtime traces given to large agents as text
(DAIRA, ADI) help, but nobody has measured how much of the executed call graph a static graph contains, or fused the
issue, static edges and executed edges in one ranking on a shared graph format.

Contributions: (1) a measurement of static-graph blind spots: half of executed calls are invisible to two independent
static graphs, in 13 classified causes; (2) RWG-PPR, an issue-seeded walk over static, AST, runtime and embedding edges
on the competition's node ids, with a pre-registered held-out evaluation against 10 baselines; (3) same-information
ablations that locate the gain; (4) where the failing test can come from: the agent's own repros, and coverage-guided
retrieval of existing tests; (5) a hinted-control study with E4B and 31B and a record of small-model harness failures; (6) a frozen-parameter
replication on SWE-bench Verified; (7) ExecGraph-129, the per-task runtime overlays, missed-edge causes, gold labels and rankings.

## 2. Method

**Tracer.** A stdlib-only in-process pytest tracer (`sys.monitoring`, or `sys.setprofile` before 3.12) records per
test the repository functions executed, every caller-to-callee pair between them (through library frames), the outcome
and the failing traceback with locals. Ids follow the competition graph's conventions, so runtime edges overlay it
directly.

**Graph.** One weighted directed graph per task over the competition graph's nodes (4.3k for fastapi). Edges: the
competition's `calls` edges (which also encode containment and inheritance); precise edges from our AST analysis
(imports and re-exports, constructors via the MRO, `self`/`super` dispatch, locally typed variables); runtime edges from
the tracer (weight 3); and k-nearest-neighbour edges from the provided embeddings (k = 5, cosine >= 0.5). Each edge has a
reverse edge at reduced weight, since the fix can lie upstream or downstream of what a test touches.

**Seeds and walk.** BM25 of the issue over each node's id tokens and source, plus a bonus for identifiers the issue
quotes. With test evidence, each seed is multiplied by (1 + 2·Ochiai) and functions executed by failing tests get a
floor, so a failing path with no textual match still seeds the walk. Personalised PageRank (restart 0.3, 50
iterations); final score = 0.3·walk + 0.7·seed. Parameters were chosen on the tuning split only.

**v2** (after the held-out split was scored once with v1): seeds also come from the failure's own text (exception
message, failing source lines, test names), restricted to executed functions; and passing tests from nearby files add
Ochiai contrast. Both are reported as exploratory.

**Evidence levels.** S: no tests run. R: the 3 existing test files nearest the issue by BM25, run on the buggy code. F:
the task's own tests after `test_patch`, run on the buggy code, which is what an agent has after writing a faithful
failing reproduction. A: the reproduction tests our E4B agent actually wrote. E1b: the full existing suite, functions per test.

## 3. Setup

All 129 public tasks (fastapi 67, rich 48, requests 13, httpx 1), run in the scorer's own sandbox and pinned
environment on Kaggle. Gold: non-test functions the reference patch edits (innermost enclosing def of each changed line
in the pre-patch file), restricted to graph nodes; 405 of 444 gold functions are nodes. The pre-registration
(`paper/prereg_e1.json`, committed before any trace existed) fixes the split, the metric (hit@5 primary), hypotheses
H1-H4 and the analysis: task-level bootstrap CIs and paired bootstrap tests. Baselines are in the Section 5 table (embedding: cosine to the top text matches; no query encoder is available offline).

## 4. What the static graph misses (D1)

Across the 129 tasks the tracer saw 42,024 distinct repo-to-repo call edges with both endpoints in the competition
graph. The competition graph contains 23.2% of them; our AST graph 49.1%; their union 50.3%. We classified each of the
20,871 edges that neither contains from the caller's AST:

| cause | share |
|---|---|
| property / descriptor access (`obj.size`) | 29.0% |
| dunder protocols (operators, `with`, iteration, `__getattr__`) | 26.6% |
| method call on a receiver of unknown type | 26.0% |
| implicit constructor (`__init__` / `__post_init__`) | 6.0% |
| unresolved name (star or conditional imports) | 3.8% |
| through library code (framework dispatch, validators) | 2.5% |
| callbacks, decorators, reflection, runtime imports | 5.4% |

Two independently built graphs miss the same edges: a static "who calls this?" is blind to half of execution, and
blindest where code is most idiomatic.

## 5. Localisation (E1)

### 5.1 Pre-registered results

Held-out split: 79 tasks with a gold node in the graph, 70 with a failing-test trace.

| ranker | evidence | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| random | - | 0.00 | 0.03 | 0.04 | 0.02 |
| BM25 | issue | 0.18 | 0.37 | 0.51 | 0.29 |
| text (BM25 + identifiers) | issue | 0.18 | 0.41 | 0.51 | 0.30 |
| embedding | issue | 0.01 | 0.09 | 0.11 | 0.06 |
| static k-hop | issue + graph | 0.18 | 0.39 | 0.52 | 0.29 |
| RWG-PPR (S) | issue + graph | 0.17 | 0.41 | 0.47 | 0.28 |
| RWG-PPR (R) | + nearby tests | 0.14 | 0.37 | 0.44 | 0.26 |
| crash frames | failing tests | 0.11 | 0.11 | 0.11 | 0.11 |
| Ochiai | failing tests | 0.09 | 0.30 | 0.41 | 0.20 |
| PRFL | failing tests | 0.17 | 0.37 | 0.56 | 0.29 |
| **RWG-PPR (F)** | **issue + failing tests** | **0.37** | **0.64** | **0.76** | **0.50** |

H3 holds: RWG-PPR (F) beats Ochiai by +0.34 [+0.23, +0.47] and PRFL by +0.27 [+0.14, +0.41] hit@5, and issue text by
+0.21 [+0.10, +0.33]. H1, H2 and H4 do not: without a failing test, neither the static graph nor traces of nearby
passing tests add anything to the issue text (RWG-PPR S 0.41 = text 0.41; R 0.37).

### 5.2 Where the gain comes from

Each pre-registered baseline saw less information than RWG-PPR (F), so after scoring we added baselines with the same
information (issue text plus failing-test spectrum). v1 scores 0.64 hit@5; with the walk off, 0.63; a weighted sum of
text and PRFL scores, 0.64.

With the same information, the walk adds nothing measurable to v1 (nor do runtime edges: 0.63). The gain is the fusion:
spectrum methods rank framework code every failing test runs (routing, validation) as high as the fix, and the issue
text breaks those ties; text alone confuses same-named functions in docs examples and the library, and the trace drops
those that never ran. The walk has little to add because the evidence already contains the answer: a failing test
executes a gold function in 60 of 72 held-out tasks.

### 5.3 v2 and a learned ranker (exploratory)

The failing test carries more than coverage: its exception message and failing lines often name the culprit. v2 seeds
from that text and adds passing-test contrast.

| held-out, n = 70 | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| RWG-PPR v2 | 0.41 | **0.77** | 0.84 | 0.55 |
| v2 without failure-text seeds | 0.37 | 0.66 | 0.74 | 0.50 |
| v2 without contrast | 0.40 | 0.71 | 0.84 | 0.54 |
| v2, walk off | 0.44 | 0.76 | 0.84 | 0.57 |
| text + failure text + PRFL (same information, no graph) | 0.37 | 0.71 | 0.86 | 0.51 |

v2 beats v1 by +0.13 [+0.04, +0.21] and its own no-failure-text ablation by +0.11 [+0.03, +0.20]. Against the
same-information combination without a graph it gains +0.06 [-0.04, +0.16], not significant; the walk alone adds
+0.01.

A LambdaRank model (LightGBM, 5-fold CV over 106 tasks with failing tests) on 22 features (text, failure text,
spectrum, graph: walk scores, degrees, hops, embedding similarity; node properties) reaches 0.80 hit@5 (v2 0.78).
Removing the graph features costs 0.057 (95% CI [0.000, 0.113]; P(no loss) = 0.03). Graph structure helps as ranker
features, not as propagation over evidence that already points at the answer.

## 6. Where the failing test comes from

Every gain above needs a failing test. Level F uses the task's own tests, which an agent does not have.

**Level A: the agent's own reproductions.** We traced the 53 reproduction tests our E4B agent wrote with `write_file`
in four dev runs (32 tasks), each alone on the buggy code in the scorer environment. 26 fail (a real reproduction,
49%); 20 pass, so they do not reproduce the bug; 7 do not import. On the 24 failing repros with gold in the graph,
RWG-PPR v2 reaches 0.71 hit@5 against 0.58 for text on the same tasks (+0.13 [0.00, +0.29], P = 0.04). Where the task
also has real failing tests, the agent's repro gets 0.81 and the real tests 0.95. A small model's reproduction is good
evidence when it reproduces; half the time it does not.

**Retrieving an existing test by coverage (E1b).**  An agent can adapt an existing test that runs the buggy code: it already has
the right imports, fixtures and call path, where E4B's own repros break. We traced the whole existing suite of 127 tasks on the buggy code (median 53 s per task;
median 2,356 tests on held-out tasks) and ranked tests using only the issue text. *cov* scores a test by the
issue-relevance of the functions it executes (RWG-PPR level-S scores, weighted by inverse test frequency, normalised by
the square root of the test's coverage); *name* is BM25 on test ids; *file R* takes the tests in level R's three
BM25-nearest files. test@k: a top-k test executes a gold function.

| held-out, n = 78 | test@1 | test@3 | test@10 |
|---|---|---|---|
| random (expected) | 0.24 | 0.41 | 0.62 |
| tests in level R's files | 0.32 | 0.38 | 0.46 |
| BM25 on test names | 0.41 | 0.67 | 0.82 |
| coverage (cov) | **0.62** | 0.73 | 0.85 |
| cov + names | 0.59 | **0.80** | **0.88** |

Ranking tests by what they execute finds a test that runs the buggy function first for 62% of tasks, against 41% by
name; combined with names, in the top 3 for 80% (+0.13 [+0.04, +0.22] over names; +0.41 over level R's file choice,
which explains why level R did not help). The executed call graph is what makes this possible: the static graph cannot
say which test reaches a function through a property or a dunder method. What does not work is using the retrieved
tests as pseudo-failing evidence for localisation: hit@5 0.46 against 0.41 for text (+0.05 [-0.04, +0.15]). A test
that passes says where the code runs, not where it is wrong; the localisation gains in Section 5 need a test that
fails. The retrieved test is a starting point for writing one.

## 7. Agents

**Hinted control (E3).** The same baseline agent (no skills, 8 minutes / 28 tool calls) on 41 dev tasks, with the
hint appended to the issue: none; the files the reference patch edits (oracle); RWG-PPR v2 top-5 with the failing
tests (rwgF). Paired per task, exact McNemar (`paper/prereg_e3.json`).

| model | none | oracle files | RWG-PPR top-5 (F) |
|---|---|---|---|
| E4B | 2/41 | 5/41 (3:0, p = 0.25) | not run (GPU quota) |
| 31B | 14/41 | 16/41 (3:1, p = 0.63) | 14/41 (2:2, p = 1.0) |

The RWG-PPR hint contained a gold function on 32 of the 37 tasks that had one; on those 32, 31B solved 12 without it,
12 with it and 12 with the oracle files. Without hints, 31B already used a median 27 of its 28 calls and ended 11 tasks with no patch, which
looked like a search bottleneck; the hint did not shorten that (median 27 calls with the hint, 24 with oracle files)
and the hinted arms timed out more often (5 and 9 sessions against 3). For this agent and budget, finding the function
is not what fails; turning a location into a correct edit within budget is. This bounds what any localiser, ours included, can add by prompting.
The E4B localiser arm and the 12B arms did not run: the weekly GPU quota ran out.

**Harness traps (E4).** Over six versions of an E4B agent with a runtime-trace skill, each harness fix removed one
failure class completely (skill name rejected on 41/41 tasks; Python-style `args=[...]` pasted into JSON tool calls, 13;
`write_file` refusing `/tmp` paths, 43 writes; the skill typed into the shell, 13), and the fix rate stayed at 3-5/41.
For a 4B model the interface between model and tools fails before the reasoning does, and none of these failures shows
in a benchmark score until it is read from the traces.

## 8. Generality: SWE-bench Verified

We reran the protocol inside the official SWE-bench Verified Docker images on all 194 tasks from its pytest
repositories (Django and SymPy use other runners), with parameters frozen and our AST graph in place of the
competition graph. 172 tasks have a failing-test trace; in 153 (89%) a failing test runs a gold function.

| hit@5 | text | Ochiai | PRFL | RWG-PPR v1 | text + PRFL | v2 | v2, walk off |
|---|---|---|---|---|---|---|---|
| 10 repos, n = 172 | 0.47 | 0.13 | 0.29 | **0.62** | 0.62 | **0.66** | 0.67 |

Everything replicates. RWG-PPR v1 beats text by +0.17 [+0.09, +0.24], PRFL by +0.34 and Ochiai by +0.49, and wins in 7
of 10 repositories (sphinx 0.56 vs 0.22; it loses on pytest, n = 9). Text + PRFL without a graph matches it, and the
walk adds nothing to v2. Without a failing test nothing beats text. The AST graph holds 42.1% of 340,028 executed edges
(30% astropy to 65% scikit-learn); the missed ones are again properties (19.8%), dunder protocols (18.9%) and unknown
receivers (16.2%). A tracer bug on Python < 3.11 (lost class names) was fixed and the run
repeated; the competition tasks (Python 3.13) were unaffected.

## 9. Limitations

- Section 8 replicates localisation on 10 more repositories, but all are Python with pytest suites; the agent and
  test-retrieval studies were not replicated there.
- v2, the learned ranker, level A and E1b were designed after the held-out split was scored once; we report them as
  exploratory, with v1 as the confirmatory result.
- Gold is function-level; 37 of 79 held-out tasks also edit module-level code, which no function ranking can find.
- E3 has 41 tasks, too few for small effects; the GPU quota ended it before the 12B arms.

## 10. Reproducibility and resource

Pre-registrations, frozen parameters, per-task outputs and analysis scripts are at github.com/shivansh193/execgraph; one Kaggle CPU
notebook regenerates every localisation number. ExecGraph-129 holds per-task runtime edges and test coverage on
competition node ids, missed-edge causes, gold labels and rankings, keyed by public upstream commits; it contains no
competition files.

## References

Abreu et al. 2007 (Ochiai); Zhang et al., ISSTA 2017 (PRFL); Xia et al., FSE 2025 (Agentless); Chen et al., ACL 2025
(LocAgent); Yu et al., ICML 2025 (OrcaLoca); Jiang et al., ASE 2025 (CoSIL); Haveliwala, WWW 2002 (personalised PageRank);
Gutierrez et al., NeurIPS 2024 (HippoRAG); Ke et al., NeurIPS 2017 (LightGBM); Jimenez et al., ICLR 2024 (SWE-bench).
