#!/usr/bin/env bash
# Open-model agent: Gemma 4 via the Gemini API (needs GEMINI_API_KEY), A (no Faultline) vs H (Faultline),
# 3 trials on e8 (large real bug) plus 1 trial each on e6/e7 (small; Faultline silent by design).
# Usage: eval/harness/run_agent_gemma.sh [model]   (default gemma-4-26b-a4b-it)
set -u
cd "$(dirname "$0")/../.."
MODEL="${1:-gemma-4-26b-a4b-it}"
[ -n "${GEMINI_API_KEY:-}" ] || [ -f "$HOME/.config/faultline/gemini_api_key" ] || { echo "set GEMINI_API_KEY or ~/.config/faultline/gemini_api_key"; exit 1; }
OUT="eval/results/agent-gemini-v2/${MODEL}"
run() { echo "$(date +%T) $1 $2 t$3"; .venv/bin/python eval/harness/run_agent_trial.py "$1" "$2" "$3" --provider gemini --model "$MODEL" --out "$OUT" | tail -1; }
for t in 1 2 3; do
  if (( t % 2 == 1 )); then run e8_ytdl A $t; run e8_ytdl H $t; else run e8_ytdl H $t; run e8_ytdl A $t; fi
done
for c in e6_invoicing e7_sessions; do run $c A 1; run $c H 1; done
