#!/bin/bash
# VM bootstrap (Ubuntu 22.04): Docker, Python deps, SWE-bench Verified task list.
set -e
sudo apt-get update -q && sudo apt-get install -y -q docker.io python3-pip git >/dev/null
sudo usermod -aG docker $USER
pip3 install -q numpy pandas pyarrow
cd ~/eg
python3 - <<'PY'
import json, urllib.request, pandas as pd, io
url = "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet"
df = pd.read_parquet(io.BytesIO(urllib.request.urlopen(url).read()))
with open("verified.jsonl", "w") as f:
    for r in df.to_dict("records"):
        f.write(json.dumps({k: (v if isinstance(v, (str, int, float, type(None))) else str(v)) for k, v in r.items()}) + "\n")
print(len(df), df.repo.value_counts().to_dict())
PY
