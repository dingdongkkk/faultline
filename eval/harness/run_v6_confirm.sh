#!/usr/bin/env bash
# v6 confirmation: Sonnet 5.5 on e6/e7/e8 and Opus 5.5 on e8; A vs H, 3 trials each (24 sessions).
# Interleaved by trial; A/H order alternates per trial and per cell.
set -u
cd "$(dirname "$0")/../.."
CELLS=("claude-sonnet-5-5 e6_invoicing" "claude-sonnet-5-5 e7_sessions" "claude-sonnet-5-5 e8_ytdl" "claude-opus-5-5 e8_ytdl")
for t in 1 2 3; do
  i=0
  for cell in "${CELLS[@]}"; do
    set -- $cell; model=$1; c=$2
    if (( (t + i) % 2 == 1 )); then order=(A H); else order=(H A); fi
    for cond in "${order[@]}"; do
      out="eval/results/v6-confirm/${model#claude-}"
      echo "$(date +%T) $model $c $cond t$t"
      .venv/bin/python eval/harness/run_trial.py "$c" "$cond" "$t" --model "$model" --out "$out" 2>&1 | tail -1
    done
    i=$((i + 1))
  done
done
