#!/usr/bin/env bash
# Open-model agent fully local: Gemma 4 12B (llama.cpp llama-server on 127.0.0.1:8089).
# A (no Faultline) vs H (Faultline context via MCP): 3 trials on e8, 1 each on e6/e7.
set -u
cd "$(dirname "$0")/../.."
OUT="eval/results/agent-local/gemma-4-12b"
run() { echo "$(date +%T) $1 $2 t$3"; .venv/bin/python eval/harness/run_agent_trial.py "$1" "$2" "$3" --provider local --out "$OUT" | tail -1; }
for t in 1 2 3; do
  if (( t % 2 == 1 )); then run e8_ytdl A $t; run e8_ytdl H $t; else run e8_ytdl H $t; run e8_ytdl A $t; fi
done
for c in e6_invoicing e7_sessions; do run $c A 1; run $c H 1; done
