#!/usr/bin/env bash
# e8, Sonnet 5.5: A x3 vs H (v6 evidence hooks + skill + MCP) x3, interleaved, order alternating.
set -u
cd "$(dirname "$0")/../.."
for spec in "H 1" "A 1" "A 2" "H 2" "H 3" "A 3"; do
  set -- $spec
  echo "$(date +%T) e8_ytdl $1 t$2"
  .venv/bin/python eval/harness/run_trial.py e8_ytdl "$1" "$2" --model claude-sonnet-5-5 --out eval/results/sonnet-v6 2>&1 | tail -1
done
