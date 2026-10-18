#!/usr/bin/env bash
# e8 (real bug, youtube-dl): A x3 and C x3, interleaved, order alternating per trial.
set -u
cd "$(dirname "$0")/../.."
for spec in "A 1" "C 1" "C 2" "A 2" "A 3" "C 3"; do
  set -- $spec
  echo "$(date +%T) e8_ytdl $1 t$2"
  .venv/bin/python eval/harness/run_trial.py e8_ytdl "$1" "$2" --out eval/results/e8 2>&1 | tail -1
done
