---
name: exec-graph
description: Run a failing test or repro under a tracer and get the functions that actually ran on the failing path, ranked, with the traceback and local values at the crash. Use after you have a failing repro and before you edit code.
---
# ExecGraph: find the bug from what actually ran

Use it once you have a failing test in `tests/test_issue_repro.py` (written with `write_file`). Call the `run_skill_script` tool with exactly:

    {"skill_name": "exec-graph", "file_path": "trace_failure.py"}

- `run_skill_script` is a tool, not a shell command: never run it through `run_command`.
- No `args` needed: it traces the newest test file you wrote. `file_path` is always the literal `trace_failure.py`.
- It also runs the closest existing test file (named in the first line of the output); its
  passing tests sharpen the ranking.
- Optional: to choose what runs, add `"args"` as a JSON list of pytest arguments, e.g.
  `{"skill_name": "exec-graph", "file_path": "trace_failure.py", "args": ["tests/test_issue_repro.py", "tests/test_x.py"]}`.
  A plain script: `"args": ["python", "/tmp/repro.py"]`. Options go first: `"args": ["--timeout", "120", ...]`.

You get back:
1. The failure: exception, repo frames from outermost to innermost, and local values in the innermost frames.
2. SUSPECTS: functions ranked by how specific they are to the failing run and how close they are to the
   exception. The names are code-graph node ids (`pkg.module.Class.method`) with `file:line`.

Then:
- Read the top 2-3 suspects (`read_file` on the given lines). An assertion failure in a test usually means the
  bug is in a suspect that computed the wrong value, not where the assert is.
- Fix in the source file, never in tests. Run the trace again after the fix: the failure should be gone.
- NOTHING FAILED: your test passes on the buggy code. Make it assert the issue's expected behaviour.
- NO TESTS RAN: a path is wrong; the output tail says which.
- If it times out, select fewer tests.
- Never copy these scripts into /workspace: anything new there ends up in your patch.

`rank_suspects.py` (args `["--top", "20"]`) re-ranks the last trace without rerunning it.
