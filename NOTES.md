# NOTES

Harness facts and deviations from SPEC.md. Sources: `HARNESS_README.md` (read in full 2026-10-30),
`docker/Dockerfile.*`, `sample_submission/`, `tasks.jsonl`, one graph file, and the competition Rules page.
Where the README and the spec disagree, the README wins.

## Status

- 2026-10-30: rules accepted on both competitions (account `shivanshkalra`). Downloads work.
- Downloaded to `data/raw/` (gitignored): HARNESS_README.md, Dockerfiles, imp.py, sandbox/setup.py,
  tasks.jsonl, sample_submission/ (configs + main_lora config), one graph. Full file list: `data/filelist.txt`.
- **Not downloaded:** 129 snapshots + 127 graphs + 127 embeddings + 124 wheels, about **22 GB**. Use them inside
  Kaggle notebooks (the dataset can be attached there), not locally.

## Deviations from SPEC.md (important first)

1. **One submission per day** (Rules §2.2a), and 2 final picks. That leaves about 33 leaderboard submissions
   until Dec 2. The spec's "log every leaderboard submission" plan still holds, but most iteration
   has to happen on a **local dev eval over tasks.jsonl** (`swegemma eval`), not on the leaderboard.
2. **Budget is per task, not 12 h overall.** The README gives no 12 h figure. Per-task defaults in `inference.py`
   are **60 min, 100 tool calls, 500 turns, 300 s per command**. Override them in `eval_config.yaml` under `evaluation:`.
   **Sandbox setup is excluded** from the agent's time budget (README §7.1). The 12 h is probably the Kaggle
   notebook runtime limit. Unconfirmed: check the Overview/Evaluation page before planning time per task.
   The sample submission uses 1 min / 10 calls, which is a demo value, not a recommendation.
3. **Local dev set exists:** `tasks.jsonl` has **129 tasks**: fastapi 67, rich 48, requests 13, httpx 1. Fields:
   `instance_id, repo, base_commit, patch, test_patch, problem_statement, hints_text, created_at`.
   There's **no FAIL_TO_PASS/PASS_TO_PASS** field; grading extracts tests from `test_patch`. `hints_text` is empty for all 129.
   Gold localisation for the paper comes from `patch` (all 129 edit at least one non-test `.py` file).
   Some tasks are **feature additions**, not bug fixes (e.g. `fastapi_15661` creates `scripts/prepare_release.py`).
   For these, "trace the failing test" only yields an ImportError, which is a known ExecGraph limit for the paper.
4. **Sandbox is Python 3.13** (`python:3.13-slim`), so `sys.monitoring` is available for the tracer.
   Container limits: **4 GiB RAM, 2 vCPU, no network**. Container A (agent) and B (verify) are separate.
5. **Skill script execution location is not documented.** ADK `SkillToolset` exposes `load_skill`,
   `load_skill_resource` and `run_skill_script`, but the README never says that `run_skill_script` runs inside
   Container A, where the repo is. The spec assumed it does. **Must verify** with a local `swegemma eval` run.
   Fallback: ship the tracer as a skill resource. The agent loads it and writes it to `/tmp` with
   `run_command` + heredoc, **not** `write_file`. **Corrected 2026-11-01:** `write_file` *rejects* any path outside
   /workspace ("Path traversal detected: '/tmp/test_repro.py' escapes workspace root"); E4B ignores the error and
   carries on. Repro tests therefore go in `tests/test_issue_repro.py` (writable, and stripped from the patch).
   A non-test `.py` written under /workspace **ends up in the patch**.
6. **Tool output cap is 5,000 chars** (run_command, graph tools, diffs). ExecGraph's output must fit about 4.5k chars.
   The context window is 32,768 tokens, with ADK compaction at 14,336 tokens.
7. **Graph format:** NetworkX node-link JSON, `{directed, multigraph, graph, nodes, edges}`. Nodes are `{id, name, text}`
   with `id == name` = dotted path (`fastapi.responses.UJSONResponse.render`). Class text has bodies elided.
   **Only edge type: `calls`.** Tests (`tests.*`) and docs examples are in the graph too. `docs_src.` is
   stripped from IDs (e.g. `settings.app02_py310.main.get_settings`). Graph files live at
   `graphs/<repo>_<commit>.json`. For the join, map the tracer's `module.__qualname__` to these IDs.
   For fastapi_016ab76: 4,287 nodes (344 `fastapi.*`, 3,270 `tests.*`) and 2,490 edges.
8. **Protected files are stripped from the patch:** `test_*.py`, `*_test.py`, `.py` under `tests/ test/ testing/`,
   `conftest.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `sitecustomize.py`, `*.pth`.
   "Don't edit tests" is enforced. **Fixes that need a pyproject.toml/setup.cfg change cannot score.**
9. **Allowed submission file extensions:** only `.yaml .yml .md .txt .py .json .safetensors`. Unpacked size **< 3 GiB**,
   10k files, 50 MiB per skill dir. Skill resources must use those extensions (no `.npz`/`.pkl` indexes).
10. **LoRA:** `adapters/<name>/{adapter_config.json, adapter_model.safetensors}`, name `[A-Za-z0-9][A-Za-z0-9._-]*`,
    **max rank 128**, served by vLLM `--lora-modules` (TP=4). Sample adapter: r=4, alpha 8, `q_proj,o_proj`,
    `base_model_name_or_path: google/gemma-4-31b-it-qat-w4a16-ct`. Whether a LoRA trained on bf16 weights loads
    cleanly on the QAT compressed-tensors base still needs a dry-run.
11. **Sampling:** don't use `thinking_level` with vLLM. Use `thinking_budget` (default 4096) + `include_thoughts`.
    `max_output_tokens` ≤ 32,768. Keep edits small to avoid cut-off `<|tool_call>`.
12. **Prize total on the Rules page is $65k** (37/18/10). The $10k Small Model bonus isn't in the rules text.
    Check that it's still listed on the Overview page.
13. **ExecGraph ranks from the trace alone; the static graph is not in the sandbox.** The graph JSON lives on the
    harness host (`data/graphs/<repo>.json`), behind the graph tools, so `rank_suspects.py` can't use graph distance.
    It ranks from the dynamic call graph instead: the trace's own caller->callee edges, Ochiai, traceback distance, and
    hops from the API under test. Suspect names use the graph's node-id format, so the agent can pass them straight to
    `get_code_neighbors`.
14. **Skill layout follows ADK, not the spec.** ADK loads `scripts/`, `references/`, `assets/` (no `resources/`), and
    the skill name must equal its directory name and be kebab-case (`exec-graph`; snake_case is behind an ADK feature flag that is off, and the first ExecGraph run failed on it). The usage notes live in the SKILL.md body
    (`load_skill` returns it), so there's no separate `how_to_use.md`. The system prompt also gives the exact
    `run_skill_script` call, which saves E4B a `load_skill` call.
15. **The local subprocess sandbox only rewrites `/workspace` and `/tmp` in shell commands,** not inside skill
    scripts. `trace_failure.py` finds the repo via `/workspace`, `$PWD` or `$PYTHONPATH`, and maps `/tmp/...` args
    to `$TMPDIR`. In the real container these are identities.
16. **ExecGraph copies /tmp repros into the repo's `tests/` while it runs** (`test_zz_execgraph_*.py`, deleted in a
    `finally`), so the repo's conftest fixtures, rootdir and pytest config apply. A leftover copy (skill call killed
    mid-run) is a protected test file and gets stripped from the patch, so it can't hurt the score.
    ADK rejects a wrong `file_path` (`SCRIPT_NOT_FOUND`) before our script runs, and `args` as a list plus
    `positional_args` (`INVALID_ARGUMENTS`); only the prompt can prevent those.

## Settled 2026-10-30 (harness source + public notebooks)

Harness source: wheels in Kaggle dataset `metric/gemma-4-developer-agent-wheelhouse`
(`swegemma-0.2.11`, `adk_submission-0.2.13`, `adk_eval_core-0.1.0`, `google_adk-1.36.1`). Unpacked locally in `data/whl/src/`.

- **Skill scripts run inside Container A** (answers deviation 5). `agent_runner.py` builds
  `AdkSandboxCodeExecutor(sandbox=context.sandbox)`, which writes `/workspace/.adk_exec_<id>.py`, runs `python3` on it and
  deletes it. ADK's wrapper unpacks the skill (`scripts/`, `references/`, `assets/`) into a **tempdir and chdirs there**,
  then `runpy`s the script with `sys.argv` from `args` (list or `--key value` dict) / `positional_args`.
  So the tracer must `cd /workspace` itself. Timeout = `timeout_seconds` (bounded by remaining task time).
- **Skill tool calls don't seem to count against `max_tool_calls`.** The executor only *checks* the budget. `run_command`
  etc. are `@budget_gated`, the SkillToolset tools are not. Verify in a dev run (`tool_calls` field of the result).
- **The 12 h total is real:** all ~120 hidden tasks (about 60 public, 1 task ≈ 0.017) must finish in 12 h on 4×L4, or the
  submission errors. A reported 4.5 min cap took about 10 h, i.e. about 0.5 min overhead per task.
- **Queue:** one pending submission per team at a time; queues have run 20+ h (staff thread 747519).
- **What scores on the public LB:** single agent, **graph tools not registered** (21/21 semantic searches returned nothing
  in one 129-task run), 8 min / 28 calls / 240 s, thinking on with `include_thoughts: true`, an early-edit rule.
  Local ablation (31B, 129 tasks): reference 48; thinking off 23; summaries off −16; tool calls 50→25 cost 14;
  analyzer sub-agent +1. Temperature/top-p/thinking budget ±3 (noise).
- **Small-model LB is weak:** best E2B/E4B public score was **0.06** (2026-10-20). The $10k Small Model prize is confirmed
  by the host's small-model leaderboard notebook (one of the two final picks must be E2B/E4B).
- **Local eval needs a scorer-like env.** A plain notebook with `sandbox='subprocess'` passes only 52/129 gold patches;
  zbigniewkirchner's hook (clean venv + scorer-image wheels + calibration) passes 127/129. `rich_3486` and
  `fastapi_14186` are impossible (contradictory skip conditions). Our dev eval uses that hook.
- **Paper competition:** a public dataset `zzgtylors/graphloc-129` already has "localization labels and agent runs" for
  the 129 tasks. Cite it and be clear about what ExecGraph adds (runtime evidence, not labels).
- Open with the organisers: whether distilling from external (non-Gemma) LLMs is allowed (thread 742807).

## Rules that affect the paper and open-sourcing

- **Data:** Apache 2.0 / any purpose, **but** you must not redistribute competition data to non-participants
  (Rules §2.4b). A public "ExecGraph dataset" built from tasks.jsonl/graphs is risky. Safer: release the
  **library** + derived metrics, and have the public Kaggle notebook (attached to the competition) load the data in place.
- **Code sharing:** private sharing outside the team is prohibited. Publicly shared competition code must also be
  posted on Kaggle (forum/notebook) (Foundational §6b). Open-sourcing ExecGraph for the Nov 12 paper
  **hands it to every competitor three weeks before Dec 2**. Decision for Shivansh.
- External data/models are allowed if public and low-cost (SWE-Gym, SWE-bench train, larger Gemma 4 as teacher = OK).
- Winner license: Apache-2.0. Use **Apache-2.0** for ExecGraph.

## Harness behaviour worth remembering

- The initial prompt includes problem, budget, env rules, graph-tool hints (only for declared tools), and a
  200-entry tree of `/workspace`. `{problem_description}` is available for instruction templating.
- `submit_patch` and `get_status` are free (don't count as tool calls). The loop ends after the turn that submits.
  Unsubmitted diffs are still scored (auto-extracted).
- 3 nudges max for text-only turns. Then the session ends.
- Put repro scripts in `/tmp` (anything new in `/workspace` that isn't a protected file goes into the patch).
- Patch must apply in Container B; resolved = pytest exit 0 **and** JUnit shows every target test passed (none skipped).
- Local eval: `swegemma eval --tasks tasks.jsonl --snapshots-dir snapshots --submission-dir ... --results-dir ...`
  writes `traces/trace_<id>.json` (ATIF), which is the source for SFT trajectories.
  `swegemma` comes from the wheelhouse dataset (see "Settled" above).

## Dev eval workflow

    python notebooks/build.py --tag e4b-base         # embeds submission/ into notebooks/dev_eval/build/
    kaggle kernels push -p notebooks/dev_eval/build  # private GPU (L4x4) kernel, internet off
    kaggle kernels output shivanshkalra/gda-dev-eval -p experiments/runs/<tag>

Defaults: 40 repo-proportional tasks (excluding the 2 impossible ones), concurrency 1
(`DEV_N_TASKS`, `DEV_CONCURRENCY`). At 8 min cap, worst case about 6 h. Results: `dev_eval_<tag>.csv/json` + harness
`results_<tag>/` (patches, traces, logs). Concurrency > 1 is untested: the env hook finds the task id via a thread-local.
