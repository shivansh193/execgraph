"""Run analysis commands on a Kaggle CPU kernel instead of the laptop.

    python notebooks/remote/build.py --cmd "python notebooks/e1/ltr.py --e1 $E1 --level F" [--cmd ...]
    kaggle kernels push -p notebooks/remote/build
    kaggle kernels output shivanshkalra/gda-analysis -p experiments/remote/<name>

The kernel recreates execgraph/, notebooks/, paper/ and experiments/e1|e3 summaries from this repo under
/kaggle/working/repo, attaches the competition data (EG_DATA) and the E1 kernel's output ($E1), runs each command
from the repo root, and leaves everything the commands write under /kaggle/working/repo/experiments.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "build"
INCLUDE = ["execgraph/execgraph/*.py", "notebooks/e1/*.py", "notebooks/e3/*.py", "paper/*.json"]

TEMPLATE = r'''
import glob, os, subprocess, sys
from pathlib import Path
FILES = {files}
CMDS = {cmds}
REPO = Path("/kaggle/working/repo")
for rel, text in FILES.items():
    p = REPO / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "lightgbm"], check=False)
env = dict(os.environ)
env["EG_DATA"] = str(Path(glob.glob("/kaggle/input/**/tasks.jsonl", recursive=True)[0]).parent)
e1 = [p for p in glob.glob("/kaggle/input/**/e1", recursive=True) if os.path.isdir(p)]
env["E1"] = next((p for p in e1 if "gda-e1-localisation" in p), "")
env["E1A"] = next((p for p in e1 if "gda-e1a-agent" in p), "")
env["E1B"] = next((p for p in e1 if "gda-e1b-full" in p), "")
print("EG_DATA", env["EG_DATA"], "E1", env["E1"], "E1A", env["E1A"], "E1B", env["E1B"], flush=True)
for c in CMDS:
    print("$", c, flush=True)
    r = subprocess.run(c, shell=True, cwd=REPO, env=env)
    print("exit", r.returncode, flush=True)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", action="append", required=True)
    ap.add_argument("--user", default="shivanshkalra")
    ap.add_argument("--kernel", default="gda-analysis")
    ap.add_argument("--source", action="append", default=[], help="extra kernel outputs to attach, e.g. gda-e1a-agent")
    a = ap.parse_args()
    files = {}
    for pat in INCLUDE:
        for p in sorted(ROOT.glob(pat)):
            files[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8")
    code = TEMPLATE.format(files=repr(files), cmds=repr(a.cmd))
    compile(code, "run.py", "exec")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run.py").write_text(code, encoding="utf-8")
    meta = {
        "id": f"{a.user}/{a.kernel}", "title": a.kernel, "code_file": "run.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": False, "enable_tpu": False,
        "enable_internet": True, "competition_sources": ["gemma-4-developer-agent"],
        "dataset_sources": [], "model_sources": [], "kernel_sources": [f"{a.user}/gda-e1-localisation"] + [f"{a.user}/{k}" for k in a.source],
    }
    (OUT / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"built {OUT} ({len(files)} files, {len(a.cmd)} commands)")


if __name__ == "__main__":
    main()
