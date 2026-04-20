#!/usr/bin/env bash
# Task 22 sweep driver. Runs `age-bakeoff run` for each pgrg retrieval mode
# under BAKEOFF_CHUNKER=hierarchy, then judges and reports. Resumable: if a
# target raw JSON already exists, that mode is skipped.
#
# Usage:
#   ./scripts/run-hier-sweep.sh                 # foreground, logs to stdout
#   LOG=logs/task22.log ./scripts/run-hier-sweep.sh
#
# Exit code is non-zero on any failure. Intermediate files under results/raw/
# and cost-*.json are left in place so a follow-up invocation can pick up
# where the failure occurred.
set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BAKEOFF_DIR"

LOG="${LOG:-/dev/stdout}"
STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-40}"
JUDGE_TIMEOUT_MIN="${JUDGE_TIMEOUT_MIN:-30}"
REPORT_TIMEOUT_MIN="${REPORT_TIMEOUT_MIN:-5}"
MODES="${MODES:-hybrid smart local global naive naive_boost}"
# SKIP_INGEST=1 reuses existing ingested state across all modes (much faster
# when the corpus is already loaded under the same chunker strategy).
SKIP_INGEST="${SKIP_INGEST:-0}"

export BAKEOFF_CHUNKER=hierarchy

log() { printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*"; }

run_one() {
    local mode="$1"
    local label="hier_${mode}"
    local raw="results/raw/scotus__${label}.json"
    if [ -f "$raw" ]; then
        log "SKIP $raw already exists"
        return 0
    fi
    local skip_flag=""
    if [ "$SKIP_INGEST" = "1" ]; then
        skip_flag="--skip-ingest"
    fi
    log "START mode=${mode} label=${label} (timeout=${STEP_TIMEOUT_MIN}m) ${skip_flag}"
    local start; start=$(date +%s)
    if timeout --kill-after=30s "${STEP_TIMEOUT_MIN}m" \
         uv run age-bakeoff run --mode "$mode" --label "$label" --corpus scotus $skip_flag; then
        local dt=$(( $(date +%s) - start ))
        log "EXIT 0 mode=${mode} (${dt}s)"
    else
        local rc=$?; local dt=$(( $(date +%s) - start ))
        log "EXIT ${rc} mode=${mode} (${dt}s) -- FAILED"
        return "$rc"
    fi
    if [ ! -f "$raw" ]; then
        log "POST-CHECK FAIL: $raw missing"
        return 2
    fi
}

main() {
    log "=== Task 22 hierarchy sweep (BAKEOFF_CHUNKER=${BAKEOFF_CHUNKER}) ==="
    for mode in $MODES; do
        run_one "$mode" || exit $?
    done
    log "=== judging ==="
    timeout "${JUDGE_TIMEOUT_MIN}m" uv run age-bakeoff judge --corpus scotus || exit $?
    log "=== reporting ==="
    timeout "${REPORT_TIMEOUT_MIN}m" uv run age-bakeoff report || exit $?
    log "=== DONE ==="
}

main "$@" 2>&1 | tee -a "$LOG"
