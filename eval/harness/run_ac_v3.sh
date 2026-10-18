#!/usr/bin/env bash
# A vs C on e6/e7, 3 trials each, interleaved; condition order alternates per trial.
set -u
echo "Historical v3 driver is retired. Current code is v4; use run_trial.py with a fresh output directory." >&2
exit 2
cd "$(dirname "$0")/../.."
for t in 1 2 3; do
  for c in e6_invoicing e7_sessions; do
    if (( t % 2 == 1 )); then order=(A C); else order=(C A); fi
    for cond in "${order[@]}"; do
      echo "$(date +%T) $c $cond t$t"
      .venv/bin/python eval/harness/run_trial.py "$c" "$cond" "$t" --out eval/results/v3 2>&1 | tail -1
    done
  done
done
