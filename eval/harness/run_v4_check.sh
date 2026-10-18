#!/usr/bin/env bash
# v4 (search_code) check: C x3 per case + A x1 per case as drift check vs v3 A. Interleaved.
set -u
cd "$(dirname "$0")/../.."
for c in e6_invoicing e7_sessions; do
  for spec in "C 1" "A 1" "C 2" "C 3"; do
    set -- $spec
    echo "$(date +%T) $c $1 t$2"
    .venv/bin/python eval/harness/run_trial.py "$c" "$1" "$2" --out eval/results/v4 2>&1 | tail -1
  done
done
