"""Build the leaderboard submission kernel: a CPU script that writes submission.zip.

    python make_submission.py                  # writes submission.zip from submission/
    python notebooks/submit/build.py           # embeds it into notebooks/submit/build/
    kaggle kernels push -p notebooks/submit/build
    kaggle competitions submit gemma-4-developer-agent -k shivanshkalra/gda-submit -f submission.zip -v <N> -m "<hash> ..."
"""
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "build"

data = (ROOT / "submission.zip").read_bytes()
digest = hashlib.sha256(data).hexdigest()[:12]
OUT.mkdir(exist_ok=True)
(OUT / "submit.py").write_text(
    f'''# Writes submission.zip (sha256 {digest}) built from the repo's submission/ tree.
import base64, hashlib
data = base64.b64decode("{base64.b64encode(data).decode()}")
assert hashlib.sha256(data).hexdigest()[:12] == "{digest}"
open("/kaggle/working/submission.zip", "wb").write(data)
print("wrote submission.zip", len(data), "bytes")
''',
    encoding="utf-8",
)
(OUT / "kernel-metadata.json").write_text(json.dumps({
    "id": "shivanshkalra/gda-submit",
    "title": "gda-submit",
    "code_file": "submit.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": False,
    "enable_tpu": False,
    "enable_internet": False,
    "competition_sources": ["gemma-4-developer-agent"],
    "dataset_sources": [],
    "model_sources": [],
    "kernel_sources": [],
}, indent=2), encoding="utf-8")
print("built", OUT, "zip sha256", digest)
