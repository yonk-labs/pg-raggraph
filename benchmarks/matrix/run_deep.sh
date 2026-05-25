#!/usr/bin/env bash
# Repeatable deep-benchmark driver for pg-raggraph.
#
# Runs the two-phase matrix sweep against the 3rd-party multi-hop benchmarks
# (MHR / MuSiQue / 2Wiki), then consolidates everything into one report.
#
#   Phase A  — retrieval mode x top_k x context-packing sweep on the staged
#              `auto` shapes (no re-ingest).
#   Phase B  — chunking-strategy axis on the structured MHR corpus
#              (re-ingests MHR once per chunker on first run).
#
# All phases use resume:true, so re-running skips already-prepared cases,
# already-staged ingest shapes, and cached judge calls. Safe to re-run after a
# crash, after tweaking a config, or to extend with more data.
#
# Judges: two local vLLM models (Qwen3-Coder @ .193, gemma-4-26B @ .133) so the
# whole sweep is cost-free. OPENAI_API_KEY is exported when available for ad-hoc
# use but the configs pin the local judges.
#
# Usage:
#   benchmarks/matrix/run_deep.sh             # both phases + report
#   PHASES="a" benchmarks/matrix/run_deep.sh  # phase A only
#   PHASES="b" benchmarks/matrix/run_deep.sh  # phase B only
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PHASES="${PHASES:-ab}"
RUNS_DIR=".matrix-runs"
LOG_DIR="${RUNS_DIR}/deep-logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

# Best-effort OpenAI key (optional; configs use local judges).
if [[ -f ../.openai ]]; then
  export OPENAI_API_KEY="$(grep '^home_key=' ../.openai | cut -d= -f2-)"
fi

run_phase() {
  local name="$1" config="$2"
  local log="${LOG_DIR}/${name}-${STAMP}.log"
  echo "[$(date +%H:%M:%S)] === Phase ${name}: ${config} === (log: ${log})"
  uv run python -m benchmarks.matrix.suite \
    --config "$config" --judge --report 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  echo "[$(date +%H:%M:%S)] Phase ${name} exit=${rc}"
  return "$rc"
}

if [[ "$PHASES" == *a* ]]; then
  run_phase "A-modes-context" "benchmarks/matrix/deep_a_modes_context.yaml"
fi
if [[ "$PHASES" == *b* ]]; then
  run_phase "B-chunkers" "benchmarks/matrix/deep_b_chunkers.yaml"
fi

# Consolidate whatever results exist into one report.
echo "[$(date +%H:%M:%S)] === Consolidating report ==="
uv run python -m benchmarks.matrix.analyze \
  --results "${RUNS_DIR}/deep-a-modes-context/llm-judge/results.jsonl" \
  --results "${RUNS_DIR}/deep-b-chunkers/llm-judge/results.jsonl" \
  --out "${RUNS_DIR}/DEEP-REPORT.md"

echo "[$(date +%H:%M:%S)] === Done. Report: ${RUNS_DIR}/DEEP-REPORT.md ==="
