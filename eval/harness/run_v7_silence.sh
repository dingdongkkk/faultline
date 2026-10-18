#!/usr/bin/env bash
# v7 silence rules: Sonnet 5.5, e6/e7, A vs H, 3 trials each (12 sessions), interleaved, order alternating.
set -u
cd "$(dirname "$0")/../.."
for t in 1 2 3; do
  i=0
  for c in e6_invoicing e7_sessions; do
    if (( (t + i) % 2 == 1 )); then order=(A H); else order=(H A); fi
    for cond in "${order[@]}"; do
      echo "$(date +%T) $c $cond t$t"
      .venv/bin/python eval/harness/run_trial.py "$c" "$cond" "$t" --model claude-sonnet-5-5 --out eval/results/v7-silence 2>&1 | tail -1
    done
    i=$((i + 1))
  done
done
