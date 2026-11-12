"""Run a failing test or repro script under the ExecGraph tracer and print ranked suspect functions.

    trace_failure.py [--timeout 90] [--top 10] [--repo /workspace] PYTEST_ARGS...
    trace_failure.py [options] python /tmp/repro.py [script args...]
    trace_failure.py                      # newest /tmp/test_*.py (or /tmp/repro*.py) + the closest test file

Pytest args are passed through (test files, node ids, -k). The full trace goes to /tmp/execgraph/trace.json;
rank_suspects.py re-ranks it without rerunning. Repros under /tmp are copied into the repo's tests/ for the run
(so conftest fixtures and pytest config apply) and removed afterwards.
"""
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))   # the skill wrapper chdirs into a tempdir; resolve first
sys.path.insert(0, HERE)
from rank_suspects import rank, render  # noqa: E402

from rank_suspects import OUT_DIR  # noqa: E402

# Keys E4B has wrapped arguments in (`args` as a dict becomes `--key value`); their values are test args.
ARG_KEYS = {"--args", "--file_path", "--file", "--files", "--path", "--paths", "--test", "--tests",
            "--test_file", "--test_files", "--positional_args", "--pytest_args", "--target", "--repro"}
SKILL_WORDS = {"exec-graph", "exec_graph", "trace_failure.py", "scripts/trace_failure.py", "pytest", "--"}


def find_repo():
    """/workspace in the task container. The local subprocess sandbox puts the repo elsewhere and only rewrites
    /workspace in shell commands, so also try $PWD (the wrapper's cwd before it chdirs) and $PYTHONPATH."""
    cands = ["/workspace", os.environ.get("PWD", ""), *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return "/workspace" if os.path.isdir("/workspace") else os.getcwd()


def tmp_dirs():
    return list(dict.fromkeys(d for d in ("/tmp", tempfile.gettempdir()) if os.path.isdir(d)))


def map_path(arg, repo):
    """Map /tmp/... and /workspace/... args to where they really are (same rewrite as the sandbox's shell), and
    bare names like `test_repro.py` to /tmp when they aren't in the repo."""
    path, sep, rest = arg.partition("::")
    real = None
    # write_file strips the leading "/", so its "/tmp/x.py" lands in <repo>/tmp/x.py
    for prefix, base in (("/tmp/", tempfile.gettempdir() + "/"), ("/tmp/", repo + "/tmp/"), ("/workspace/", repo + "/")):
        if real is None and path.startswith(prefix) and not os.path.exists(path) and os.path.exists(base + path[len(prefix):]):
            real = base + path[len(prefix):]
    if real is None and path.endswith(".py") and not os.path.isabs(path) and not os.path.exists(os.path.join(repo, path)):
        real = next((os.path.join(d, os.path.basename(path)) for d in tmp_dirs() + [os.path.join(repo, "tmp")]
                     if os.path.exists(os.path.join(d, os.path.basename(path)))), None)
    return (real or path) + sep + rest


def split_value(v):
    """`--positional_args "['a.py', 'b.py']"` arrives as one string; also accept 'a.py b.py' and 'a.py,b.py'."""
    v = v.strip()
    if v[:1] in "[(":
        try:
            return [str(x) for x in ast.literal_eval(v)]
        except (ValueError, SyntaxError):
            v = v.strip("[]()")
    return [p.strip("'\" ") for p in re.split(r"[\s,]+", v) if p.strip("'\" ")]


def normalise(argv):
    """Turn whatever the model sent into (options, pytest-or-script args)."""
    opts, out, it = {}, [], iter(argv)
    for a in it:
        a = str(a).strip()
        if a in ("--timeout", "--top", "--repo"):
            opts[a] = next(it, "")
        elif a == "-k":
            out += ["-k", str(next(it, ""))]
        elif a in ARG_KEYS:
            out += split_value(next(it, ""))
        elif a.startswith("--") and "=" in a and a.split("=", 1)[0] in ARG_KEYS:
            out += split_value(a.split("=", 1)[1])
        elif a in SKILL_WORDS or not a or os.path.basename(a) in ("trace_failure.py", "rank_suspects.py"):
            continue
        elif " " in a and not a.startswith("-k"):   # "pytest /tmp/x.py tests/y.py" given as one string
            out += [p for p in split_value(a) if p not in SKILL_WORDS]
        else:
            out.append(a.strip("'\""))
    return opts, out


def untracked(repo):
    """New .py files the agent created in the repo (repros written with write_file end up here)."""
    try:
        out = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {os.path.normpath(os.path.join(repo, line)) for line in out.splitlines() if line.endswith(".py")}


def is_repro(path, repo, new):
    """A test the agent wrote: outside the repo, or a new untracked file inside it."""
    p = os.path.normpath(os.path.abspath(path))
    return os.path.relpath(p, repo).startswith("..") or p in new


def newest_repro(repo, new):
    found = [p for d in tmp_dirs() for pat in ("test_*.py", "*repro*.py") for p in glob.glob(os.path.join(d, pat))]
    found += [p for p in new if re.match(r"(test_.*|.*repro.*)\.py$", os.path.basename(p))
              and "execgraph" not in os.path.basename(p)]
    return max(found, key=os.path.getmtime) if found else None


def is_repo_test(path, repo):
    rel = os.path.relpath(os.path.abspath(path), repo)
    return not rel.startswith("..") and (rel.startswith(("tests", "test")) or os.path.basename(rel).startswith("test_"))


def closest_test_file(repro, repo, created):
    """The existing repo test file (not one the agent wrote) that mentions the most names the repro imports."""
    try:
        tree = ast.parse(open(repro, encoding="utf-8").read())
    except (OSError, SyntaxError, ValueError):
        return None
    names = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
             and not n.module.startswith(("pytest", "typing", "unittest")) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and "." in n.module}
    names = {n for n in names if len(n) > 3}
    if not names:
        return None
    best, score = None, 0
    for p in glob.glob(os.path.join(repo, "tests", "**", "test_*.py"), recursive=True):
        if os.path.normpath(p) in created or os.path.normpath(p) == os.path.normpath(os.path.abspath(repro)):
            continue
        try:
            if os.path.getsize(p) > 400_000:
                continue
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        s = sum(1 for n in names if re.search(r"\b%s\b" % re.escape(n), text))
        if s > score or (s == score and best and len(p) < len(best)):
            best, score = p, s
    return os.path.relpath(best, repo) if best else None


def has_tests(path):
    try:
        return bool(re.search(r"^\s*(async\s+)?def test|^class Test", open(path, encoding="utf-8").read(), re.M))
    except OSError:
        return False


def stage_repros(args, repo, created):
    """Copy pytest repros that live outside the repo into tests/ so rootdir, pytest config and conftest apply.
    Returns (new args, copies to delete, display renames)."""
    dest_dir = os.path.join(repo, "tests") if os.path.isdir(os.path.join(repo, "tests")) else repo
    new, copies, renames = [], [], {}
    for a in args:
        path, sep, rest = a.partition("::")
        in_tests = os.path.relpath(os.path.abspath(path), repo).replace(os.sep, "/").startswith("tests/")
        if path.endswith(".py") and os.path.isfile(path) and is_repro(path, repo, created) and not in_tests:
            dst = os.path.join(dest_dir, "test_zz_execgraph_" + os.path.basename(path).removeprefix("test_"))
            shutil.copyfile(path, dst)
            copies.append(dst)
            rel = os.path.relpath(dst, repo).replace(os.sep, "/")
            for alias in (dst, os.path.relpath(dst, repo), rel):
                renames[alias] = path
            renames[rel[:-3].replace("/", ".")] = os.path.basename(path)[:-3]   # module part of node ids
            new.append(rel + sep + rest)
        else:
            new.append(a)
    return new, copies, renames


def unstage(text, renames):
    """Show the agent its own repro paths, not the staged copies (longest alias first)."""
    for alias in sorted(renames, key=len, reverse=True):
        text = text.replace(alias, renames[alias])
    return text


def run(mode, rest, repo, timeout):
    raw = os.path.join(OUT_DIR, "trace.json")
    if os.path.exists(raw):
        os.remove(raw)
    cmd = [task_python(), os.path.join(HERE, "_tracer.py"), raw, repo, mode, *rest]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=timeout)
    trace = None
    if os.path.exists(raw):
        with open(raw) as f:
            trace = json.load(f)
    return proc, trace, raw


def task_python():
    """The interpreter the repo's tests run on: the one next to `pytest`, else `python` on PATH."""
    pt = shutil.which("pytest")
    if pt:
        cand = os.path.join(os.path.dirname(pt), "python")
        if os.path.exists(cand):
            return cand
    return shutil.which("python") or shutil.which("python3") or sys.executable


def main(argv):
    opts, args = normalise(argv)
    timeout, top = int(opts.get("--timeout") or 90), int(opts.get("--top") or 10)
    repo = opts.get("--repo") or find_repo()
    notes, new = [], untracked(repo)
    if not args:
        repro = newest_repro(repo, new)
        if not repro:
            print("ExecGraph: no reproduction test found. write_file a failing test to tests/test_issue_repro.py "
                  "(a /tmp path is rejected by write_file), then call this skill again with the same two arguments.")
            return 0
        args = [repro]
        notes.append(f"no args given: traced newest repro {repro}")
    args = [map_path(a, repo) for a in args]
    missing = [p for p in (a.partition("::")[0] for a in args) if p.endswith(".py")
               and not os.path.exists(p) and not os.path.exists(os.path.join(repo, p))]
    if missing:
        print(f"ExecGraph: {', '.join(missing)} does not exist. write_file your failing test first, to "
              "tests/test_issue_repro.py, e.g.\nfrom <package>.<module> import <name>\n\ndef test_issue():\n"
              "    assert <call from the issue> == <expected value>\nthen call this skill again.")
        return 0

    if args[0] in ("python", "python3"):
        mode, rest = "script", args[1:]
        if rest and has_tests(rest[0]) and "__main__" not in open(rest[0], encoding="utf-8").read():
            mode = "pytest"   # a test file run as a script only defines its tests; run them instead
            notes.append(f"{rest[0]} only defines tests, so it was run with pytest")
    elif args[0].endswith(".py") and os.path.isfile(args[0]) and "::" not in args[0] \
            and not is_repo_test(args[0], repo) and not has_tests(args[0]):
        mode, rest = "script", args          # a plain script with no test functions
    else:
        mode, rest = "pytest", args

    copies, renames, auto = [], {}, None
    if mode == "pytest":
        files = [a.partition("::")[0] for a in rest if a.partition("::")[0].endswith(".py")]
        repros = [f for f in files if os.path.isfile(f) and is_repro(f, repo, new)]
        if repros and len(repros) == len(files):   # only repros: add the closest existing test file for contrast
            auto = closest_test_file(repros[0], repo, new)
            if auto:
                rest = rest + [auto]
                notes.append(f"added closest test file {auto} (its passing tests sharpen the ranking)")
        rest, copies, renames = stage_repros(rest, repo, new)

    os.makedirs(OUT_DIR, exist_ok=True)
    shown = ("pytest " if mode == "pytest" else "python ") + " ".join(rest)
    try:
        try:
            proc, trace, raw = run(mode, rest, repo, timeout)
        except subprocess.TimeoutExpired:
            if not auto:
                print(f"ExecGraph: `{shown}` timed out after {timeout}s. Select fewer tests (one file or -k) and retry.")
                return 0
            rest.remove(auto)
            notes.append(f"dropped {auto}: too slow")
            shown = "pytest " + " ".join(rest)
            try:
                proc, trace, raw = run(mode, rest, repo, timeout)
            except subprocess.TimeoutExpired:
                print(f"ExecGraph: `{shown}` timed out after {timeout}s. Select fewer tests and retry.")
                return 0
    finally:
        for c in copies:
            if os.path.exists(c):
                os.remove(c)
    shown = unstage(shown, renames)
    out_tail = unstage((proc.stdout + proc.stderr).strip(), renames)
    if trace is None:
        print(f"ExecGraph: tracer crashed (exit {proc.returncode}) on `{shown}`. Output tail:\n{out_tail[-1500:]}")
        return 0
    trace["cmd"] = shown
    with open(raw, "w") as f:
        json.dump(trace, f)
    text = unstage(render(trace, rank(trace, top), shown), renames)
    if notes:
        text = "\n".join(f"note: {n}" for n in notes) + "\n" + text
    failed = any(t["outcome"] == "failed" for t in trace["tests"].values()) or trace["failures"]
    if not failed and trace["exit_code"] in (2, 3, 4, 5):   # usage error / nothing collected: not a passing repro
        text = re.sub(r"NOTHING FAILED:.*", "NO TESTS RAN: pytest could not collect what you passed (see the output "
                      "tail). Check the paths: your repro in /tmp, existing tests under tests/.", text)
    if not failed:
        ran =[t for t, v in trace["tests"].items() if v["outcome"] == "passed"]
        text += "\npassed: " + (", ".join(unstage(t, renames) for t in ran[:6]) or "none (no test was collected)")
    if (not failed or trace["exit_code"] not in (0, 1)) and out_tail:
        text += f"\n\noutput tail:\n{out_tail[-900:]}"
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
