#!/usr/bin/env bash
# v8 capture: e8, A vs H (capture hooks + skill + MCP), Sonnet 5.5 and Opus 5.5, 3 trials each (12 sessions).
set -u
cd "$(dirname "$0")/../.."
for t in 1 2 3; do
  i=0
  for model in claude-sonnet-5-5 claude-opus-5-5; do
    if (( (t + i) % 2 == 1 )); then order=(A H); else order=(H A); fi
    for cond in "${order[@]}"; do
      echo "$(date +%T) $model e8_ytdl $cond t$t"
      .venv/bin/python eval/harness/run_trial.py e8_ytdl "$cond" "$t" --model "$model" --out "eval/results/v8-capture/${model#claude-}" 2>&1 | tail -1
    done
    i=$((i + 1))
  done
done
