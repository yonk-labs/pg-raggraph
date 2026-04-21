#!/usr/bin/env bash
# Launch the 7 remaining GraphRAG-Bench medical mode runs sequentially.
# Assumes hybrid run has completed and ingested data is in both engines.
#
# Uses local Qwen for answer + judge (per .env BAKEOFF_*_BASE_URL). Zero
# OpenAI cost on these runs. Hybrid run (label=hybrid) already completed
# against gpt-5-mini as the gold quality anchor.
#
# Env:
#   STEP_TIMEOUT_MIN (default 45)
#
# Total wall clock: ~1 hour (5 pgrg × ~7 min + 2 AGE × ~7 min).

set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BAKEOFF_DIR"

if [ -f .env ]; then set -a; . .env; set +a; fi
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"

STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-90}"
LOG_DIR="${BAKEOFF_DIR}/logs"
mkdir -p "$LOG_DIR"

log() { printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*"; }

run_one() {
    local label="$1" mode="$2" engines="$3"
    local log="${LOG_DIR}/gb-medical-${label}.log"
    log "=== $label (mode=$mode engines=$engines) -> $log ==="
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

# 5 pgrg-only modes (the retrieval-mode sweep)
run_one naive        naive        pgrg
run_one naive_boost  naive_boost  pgrg
run_one local        local        pgrg
run_one global       global       pgrg
run_one smart        smart        pgrg

# 2 AGE-only modes (AGE's label space: age_<mode>)
run_one age_local    local        age
run_one age_global   global       age

log "=== all done ==="
ls -la results/raw/graphrag-bench-medical*.json
