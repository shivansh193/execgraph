#!/bin/bash
# Whole unattended job on the VM: setup, smoke test on 2 tasks, full run, scoring. Log: ~/eg/job.log
cd ~ && mkdir -p eg && tar xzf eg.tgz -C eg && cd eg
bash notebooks/swebench/vm_setup.sh
echo "== smoke $(date)"
sudo python3 notebooks/swebench/run.py --tasks verified.jsonl --out out --limit 2 --jobs 2
for d in out/*/; do python3 -c "import json,sys;m=json.load(open('$d/meta.json'));print('$d',m.get('error'),m.get('python'),(m.get('R') or {}).get('ok'),(m.get('F') or {}).get('ok'),((m.get('F') or {}).get('tail') or '')[-300:])"; done
echo "== full $(date)"
sudo python3 notebooks/swebench/run.py --tasks verified.jsonl --out out --jobs 6
echo "== score $(date)"
python3 notebooks/swebench/score.py --out out --tasks verified.jsonl > score.txt 2>&1
tar czf results.tgz score.txt swebench_rows.json out/*/meta.json out/*/runtime_edges.json
echo "== done $(date)"
