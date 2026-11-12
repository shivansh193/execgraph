#!/bin/bash
# Push prebuilt kernels in order, waiting for a free GPU slot (Kaggle: 2 batch GPU sessions per account).
# usage: bash notebooks/e3/queue.sh gda-e3-31b-none gda-e3-31b-goldfile ...
cd "$(dirname "$0")/../.."
for k in "$@"; do
  while true; do
    out=$(timeout 120 kaggle kernels push -p notebooks/e3/build/$k 2>&1 | grep -v "outdated" | tail -1)
    case "$out" in
      *successfully*) echo "$(date +%H:%M) pushed $k"; break;;
      *"Maximum batch GPU"*) sleep 240;;
      *) echo "$(date +%H:%M) $k: $out"; sleep 120;;
    esac
  done
done
echo "$(date +%H:%M) queue empty"
