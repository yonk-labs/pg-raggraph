#!/usr/bin/env bash
# Re-run the 7 medical modes with gpt-5-mini as answer model.
# Hybrid already ran against mini; this backfills the other 7.
#
# Judge stays local Qwen (matches mini 8-9/10 per cross-validation).
# Extraction stays local Qwen (already cached from prior run).
#
# Cost: ~$30-40 total ($4-6 per mode × 7 modes, pgrg-only gets --engines pgrg).
# Wall: ~3 hours (each mode ~25-30 min on OpenAI).

set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BAKEOFF_DIR"

if [ -f .env ]; then set -a; . .env; set +a; fi

# Override answer endpoint to OpenAI.
# pydantic-settings env_file=".env" on BakeoffConfig re-reads .env inside the
# subprocess and re-exports keys that were unset in the parent shell — so
# `unset` isn't enough. Explicit empty-string assignment survives the
# re-read because .env only sets unset vars (set -a/+a semantics don't
# clobber already-set ones, and pydantic-settings' _load_env_file doesn't
# overwrite existing env). Judge + extraction keep local Qwen.
export BAKEOFF_ANSWER_BASE_URL=""
export BAKEOFF_ANSWER_MODEL=gpt-5-mini
export GRAPHRAG_API_KEY="${GRAPHRAG_API_KEY:-${OPENAI_API_KEY:-}}"

STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-90}"
LOG_DIR="${BAKEOFF_DIR}/logs"
mkdir -p "$LOG_DIR"

log() { printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*"; }

run_one() {
    local label="$1" mode="$2" engines="$3"
    local log="${LOG_DIR}/gb-medical-${label}-mini.log"
    log "=== $label (mode=$mode engines=$engines answer=mini) -> $log ==="
    if timeout --kill-after=30s "${STEP_TIMEOUT_MIN}m" \
         uv run age-bakeoff run \
         --corpus graphrag-bench-medical \
         --mode "$mode" \
         --label "$label" \
         --skip-ingest \
         --engines "$engines" \
         -n 1 \
         > "$log" 2>&1; then
        log "=== OK $label ==="
    else
        local rc=$?
        log "=== FAIL $label (exit $rc) ==="
        tail -20 "$log"
    fi
}

run_one naive        naive        pgrg
run_one naive_boost  naive_boost  pgrg
run_one local        local        pgrg
run_one global       global       pgrg
run_one smart        smart        pgrg
run_one age_local    local        age
run_one age_global   global       age

log "=== all done ==="
ls -la results/raw/graphrag-bench-medical*.json
