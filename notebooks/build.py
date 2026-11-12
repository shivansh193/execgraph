"""Embed submission/ into the dev-eval Kaggle script and write its kernel metadata.

    python notebooks/build.py --tag e4b-base          # writes notebooks/dev_eval/build/
    kaggle kernels push -p notebooks/dev_eval/build   # runs on Kaggle (uses GPU quota)
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from make_submission import SRC, config_hash, files, validate  # noqa: E402

TEMPLATE = ROOT / "notebooks" / "dev_eval" / "dev_eval.py"
OUT = ROOT / "notebooks" / "dev_eval" / "build"
MODELS = ("31b", "12b", "e4b", "e2b")
STARTER_IMAGE = (
    "gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="run tag, e.g. e4b-base")
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--user", default="shivanshkalra")
    ap.add_argument("--model", help="override agent.yaml's model, e.g. gemma-4-31b-it-qat-w4a16-ct")
    ap.add_argument("--hints", type=Path, help="JSON {task id: text appended to the problem statement}")
    ap.add_argument("--tasks", type=Path, help="JSON list of task ids to run instead of the default subset")
    ap.add_argument("--kernel", default="gda-dev-eval", help="kernel slug; distinct slugs run in parallel")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    errors = validate(args.src)
    if errors:
        print("\n".join("ERROR: " + e for e in errors))
        return 1
    bundle = {p.relative_to(args.src).as_posix(): p.read_text(encoding="utf-8") for p in files(args.src)}
    tag = f"{args.tag}-{config_hash(args.src)}"
    if args.model:
        y = bundle["agent.yaml"]
        bundle["agent.yaml"] = re.sub(r"(?m)^model:.*$", f"model: {args.model}", y, count=1)
        assert bundle["agent.yaml"] != y or f"model: {args.model}" in y
    code = TEMPLATE.read_text(encoding="utf-8")
    code = code.replace("SUBMISSION_FILES = {}  # filled in by build.py", f"SUBMISSION_FILES = {bundle!r}", 1)
    code = code.replace("RUN_TAG = 'dev'        # filled in by build.py", f"RUN_TAG = {tag!r}", 1)
    if args.hints:
        hints = json.loads(args.hints.read_text(encoding="utf-8"))
        code = code.replace("HINTS = {}             # filled in by build.py", f"HINTS = {hints!r}", 1)
    if args.tasks:
        ids = json.loads(args.tasks.read_text(encoding="utf-8"))
        code = code.replace("TASK_IDS = []          # filled in by build.py", f"TASK_IDS = {ids!r}", 1)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev_eval.py").write_text(code, encoding="utf-8")
    meta = {
        "id": f"{args.user}/{args.kernel}",
        "title": args.kernel,
        "code_file": "dev_eval.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": False,
        "machine_shape": "NvidiaL4",
        # The starter notebook's image (Python 3.12). The latest image is 3.13 and the cp312 wheelhouse won't install.
        "docker_image": STARTER_IMAGE,
        "docker_image_pinning_type": "original",
        "competition_sources": ["gemma-4-developer-agent"],
        "dataset_sources": [
            "metric/gemma-4-developer-agent-wheelhouse",
            "zbigniewkirchner/gemma-4-agent-local-eval-wheels",
            "zbigniewkirchner/gemma-4-agent-local-eval-pythons",
        ],
        "model_sources": [f"google/gemma-4/Other/gemma-4-{m}-it-qat-w4a16-ct/2" for m in MODELS],
        "kernel_sources": [],
    }
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"built {out} (run tag {tag}, {len(bundle)} bundle files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
