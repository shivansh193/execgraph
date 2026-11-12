"""Build the E1 Kaggle kernel (CPU): dev_eval.py's harness + scorer-like env, then notebooks/e1/e1_main.py.

    python notebooks/e1/build.py                 # writes notebooks/e1/build/
    kaggle kernels push -p notebooks/e1/build
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "notebooks"))
from build import STARTER_IMAGE  # noqa: E402
from make_submission import SRC, files  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "build"
DEV_EVAL = ROOT / "notebooks" / "dev_eval" / "dev_eval.py"
CUT = "# ---------------------------------------------------------------- 3b."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="shivanshkalra")
    ap.add_argument("--only", default="", help="comma-separated task ids, for a smoke run")
    ap.add_argument("--agent", type=Path, help="agent repros JSON: run level A only (experiments/e1a/agent_repros.json)")
    ap.add_argument("--kernel", default="gda-e1-localisation")
    ap.add_argument("--full", action="store_true", help="E1b: trace each task's whole existing test suite")
    args = ap.parse_args()

    base = DEV_EVAL.read_text(encoding="utf-8")
    assert CUT in base, "dev_eval.py section 3b marker moved"
    base = base.split(CUT)[0]
    bundle = {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in files(SRC)}
    base = base.replace("SUBMISSION_FILES = {}  # filled in by build.py", f"SUBMISSION_FILES = {bundle!r}", 1)

    eg = {p.relative_to(ROOT / "execgraph").as_posix(): p.read_text(encoding="utf-8")
          for p in (ROOT / "execgraph" / "execgraph").glob("*.py")}
    body = (HERE / "e1_main.py").read_text(encoding="utf-8")
    body = body.replace("EXECGRAPH_FILES = {}  # filled in by build.py", f"EXECGRAPH_FILES = {eg!r}", 1)
    body = body.replace("E1_TASK_SRC = ''      # filled in by build.py",
                        f"E1_TASK_SRC = {(HERE / 'e1_task.py').read_text(encoding='utf-8')!r}", 1)
    tracer = ROOT / "submission" / "skills" / "exec-graph" / "scripts" / "_tracer.py"
    body = body.replace("TRACER_SRC = ''       # filled in by build.py",
                        f"TRACER_SRC = {tracer.read_text(encoding='utf-8')!r}", 1)
    if args.agent:
        reps = json.loads(args.agent.read_text(encoding="utf-8"))
        body = body.replace("AGENT_REPROS = {}     # filled in by build.py", f"AGENT_REPROS = {reps!r}", 1)
    if args.full:
        body = body.replace("FULL_SUITE = False    # filled in by build.py", "FULL_SUITE = True", 1)
    if args.only:
        body = f"os.environ.setdefault('E1_ONLY', {args.only!r})\n" + body
    code = base + body

    compile(code, "e1.py", "exec")   # before writing anything, so a broken build can't be pushed
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e1.py").write_text(code, encoding="utf-8")
    meta = {
        "id": f"{args.user}/{args.kernel}",
        "title": args.kernel,
        "code_file": "e1.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": False,
        "enable_tpu": False,
        "enable_internet": False,
        "docker_image": STARTER_IMAGE,
        "docker_image_pinning_type": "original",
        "competition_sources": ["gemma-4-developer-agent"],
        "dataset_sources": [
            "metric/gemma-4-developer-agent-wheelhouse",
            "zbigniewkirchner/gemma-4-agent-local-eval-wheels",
            "zbigniewkirchner/gemma-4-agent-local-eval-pythons",
        ],
        "model_sources": [],
        "kernel_sources": [],
    }
    (OUT / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"built {OUT / 'e1.py'} ({len(code) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
