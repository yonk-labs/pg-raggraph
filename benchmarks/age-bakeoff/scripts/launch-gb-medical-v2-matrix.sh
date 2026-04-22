#!/usr/bin/env bash
# V2 medical re-run: 8-mode × engine-appropriate × 100Q on gpt-5-mini via work_key.
#
# Replaces the v1 "broken chunker" run. Uses the fixed hierarchy chunker (cap
# + paragraph-aware sub-split + metadata.heading/section_part). Extraction and
# ingest already completed under the new chunker; this script only runs the
# answer + judge legs.
#
# Cost: estimated $35-50 for answers + $10-15 for judge ≈ $50-65 total.
# Wall: ~3.5-4 hours. Each mode ~25-30 min, judge ~20-30 min at end.

set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BAKEOFF_DIR"
if [ -f .env ]; then set -a; . .env; set +a; fi

# Route answer + judge + extraction to OpenAI via work_key. Empty-string
# BAKEOFF_*_BASE_URL is the explicit signal that survives pydantic-settings'
# .env re-read (see commit bd232ca).
export BAKEOFF_ANSWER_BASE_URL=""
export BAKEOFF_ANSWER_MODEL=gpt-5-mini
# Disable chunk truncation — gpt-5-mini handles the ~2KB hierarchy chunks
# natively and the smaller chunks mean retrieved context is already small.
export BAKEOFF_ANSWER_CHUNK_CHARS=0
export BAKEOFF_JUDGE_BASE_URL=""
export BAKEOFF_JUDGE_MODEL=gpt-5-mini
OPENAI_API_KEY="$(grep ^work_key= /home/yonk/yonk-tools/.openai | cut -d= -f2)"
export OPENAI_API_KEY
export GRAPHRAG_API_KEY="$OPENAI_API_KEY"

STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-90}"
LOG_DIR="${BAKEOFF_DIR}/logs"
mkdir -p "$LOG_DIR"
MASTER_LOG="${LOG_DIR}/gb-medical-v2-matrix.log"

log() {
    printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*" | tee -a "$MASTER_LOG"
}

run_one() {
    local label="$1" mode="$2" engines="$3"
    local log="${LOG_DIR}/gb-medical-v2-${label}.log"
    log "=== $label (mode=$mode engines=$engines) -> $log ==="
    if timeout --kill-after=30s "${STEP_TIMEOUT_MIN}m" \
         uv run age-bakeoff run \
         --corpus graphrag-bench-medical \
         --mode "$mode" \
         --label "$label" \
         --skip-ingest \
         --engines "$engines" \
         --budget-usd 75 \
         -n 1 \
         > "$log" 2>&1; then
        log "=== OK $label ==="
    else
        local rc=$?
        log "=== FAIL $label (exit $rc) ==="
        tail -20 "$log" | tee -a "$MASTER_LOG"
    fi
}

log "=== v2 medical matrix start (work_key, gpt-5-mini answer+judge) ==="

run_one naive        naive        pgrg
run_one naive_boost  naive_boost  pgrg
run_one local        local        pgrg
run_one global       global       pgrg
run_one smart        smart        pgrg
run_one hybrid       hybrid       pgrg,age
run_one age_local    local        age
run_one age_global   global       age

log "=== all answer runs done; judging... ==="

uv run age-bakeoff judge --corpus graphrag-bench-medical --budget-usd 25 \
    > "${LOG_DIR}/gb-medical-v2-judge.log" 2>&1
JUDGE_RC=$?
if [ "$JUDGE_RC" -eq 0 ]; then
    log "=== judge OK ==="
else
    log "=== judge FAILED (exit $JUDGE_RC) ==="
    tail -20 "${LOG_DIR}/gb-medical-v2-judge.log" | tee -a "$MASTER_LOG"
fi

log "=== DONE. Raw + judge files: ==="
ls -la results/raw/graphrag-bench-medical*.json results/judge/graphrag-bench-medical*.json 2>&1 | tee -a "$MASTER_LOG"

log "=== v2 medical matrix complete ==="
