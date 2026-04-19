#!/usr/bin/env bash
# Runs a sequence of `age-bakeoff run --mode X --label Y --corpus Z` steps
# with per-step timeout, output verification, and diagnostic dump on failure.
#
# Per-step guarantees:
#   - timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m wraps every `run`
#   - after exit, raw JSON existence + record count are verified
#   - on failure, diagnostics are dumped to /tmp/bakeoff-stall-<ts>-<tag>/
#
# Usage:
#   ./scripts/run-mode-sweep.sh                 # runs the default sweep below
#   LOG=/tmp/foo.log ./scripts/run-mode-sweep.sh
#
# Exit code is non-zero on any failure. Cost trackers and raw/ JSONs are
# left in place so a follow-up run can skip completed steps.
set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${LOG:-/tmp/naive-boost-sweep.log}"
STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-45}"
JUDGE_TIMEOUT_MIN="${JUDGE_TIMEOUT_MIN:-30}"
REPORT_TIMEOUT_MIN="${REPORT_TIMEOUT_MIN:-5}"
EXPECTED_RECORDS="${EXPECTED_RECORDS:-180}"

cd "$BAKEOFF_DIR"

log()  { printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*" | tee -a "$LOG"; }

dump_diagnostics() {
    local tag="$1"
    local ts
    ts="$(date +%Y%m%d-%H%M%S)"
    local dir="/tmp/bakeoff-stall-${ts}-${tag}"
    mkdir -p "$dir"
    log "DIAGNOSTIC DUMP -> $dir"
    tail -200 "$LOG" > "$dir/log-tail.txt" 2>&1 || true
    ps -ef | grep -iE "age-bakeoff|uv run|python" | grep -v grep > "$dir/ps.txt" 2>&1 || true
    docker stats --no-stream > "$dir/docker-stats.txt" 2>&1 || true
    for container in age-bakeoff-pgrg age-bakeoff-age; do
        local db; db="$(echo "$container" | tr - _)"
        docker exec "$container" psql -U postgres -d "$db" \
            -c "SELECT pid, state, state_change, xact_start, query_start, LEFT(query,120) AS q FROM pg_stat_activity WHERE state != 'idle' OR xact_start IS NOT NULL;" \
            > "$dir/${container}-activity.txt" 2>&1 || true
        docker exec "$container" psql -U postgres -d "$db" \
            -c "SELECT pid, mode, granted, relation::regclass FROM pg_locks WHERE NOT granted LIMIT 30;" \
            > "$dir/${container}-blocked-locks.txt" 2>&1 || true
    done
    df -h / /tmp > "$dir/disk.txt" 2>&1 || true
    log "  -> diagnostics saved"
}

verify_output() {
    local raw="$1"
    if [ ! -f "$raw" ]; then
        log "  FAIL: expected output $raw not found"
        return 1
    fi
    local count
    count="$(python3 -c "import json; print(len(json.load(open('$raw'))))" 2>/dev/null || echo "?")"
    if [ "$count" != "$EXPECTED_RECORDS" ]; then
        log "  FAIL: $raw has $count records, expected $EXPECTED_RECORDS"
        return 1
    fi
    log "  OK verified: $raw ($count records)"
    return 0
}

preflight() {
    log "=== PREFLIGHT ==="
    if ! uv run age-bakeoff --help > /dev/null 2>&1; then
        log "  FAIL: age-bakeoff CLI not responding"
        return 1
    fi
    log "  OK: CLI responds"
    for c in age-bakeoff-pgrg age-bakeoff-age; do
        if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
            log "  FAIL: container $c not running"
            return 1
        fi
    done
    log "  OK: both containers running"
    for corpus in acme scotus; do
        if [ ! -f "corpora/$corpus/extraction_cache.json" ]; then
            log "  WARN: corpora/$corpus/extraction_cache.json missing (ingest will call LLM)"
        fi
    done
    log "=== PREFLIGHT OK ==="
}

run_step() {
    local mode="$1" label="$2" corpus="$3"
    local tag="${corpus}__${label}"
    local raw="results/raw/${corpus}__${label}.json"

    log "=== START $tag (mode=$mode, timeout=${STEP_TIMEOUT_MIN}m) ==="
    local start; start="$(date +%s)"

    if timeout --kill-after=30s "${STEP_TIMEOUT_MIN}m" \
         uv run age-bakeoff run --mode "$mode" --label "$label" --corpus "$corpus" \
         >> "$LOG" 2>&1; then
        local elapsed=$(( $(date +%s) - start ))
        log "=== EXIT 0 $tag (${elapsed}s) ==="
    else
        local rc=$?
        log "=== EXIT $rc $tag (TIMEOUT or ERROR) ==="
        dump_diagnostics "$tag"
        return "$rc"
    fi

    verify_output "$raw" || { dump_diagnostics "$tag-verify"; return 2; }
}

run_judge() {
    log "=== START judge ==="
    if timeout "${JUDGE_TIMEOUT_MIN}m" uv run age-bakeoff judge --corpus acme --corpus scotus >> "$LOG" 2>&1; then
        log "=== EXIT 0 judge ==="
    else
        local rc=$?
        log "=== EXIT $rc judge ==="
        dump_diagnostics "judge"
        return "$rc"
    fi
}

run_report() {
    log "=== START report ==="
    if timeout "${REPORT_TIMEOUT_MIN}m" uv run age-bakeoff report >> "$LOG" 2>&1; then
        log "=== EXIT 0 report ==="
    else
        local rc=$?
        log "=== EXIT $rc report ==="
        dump_diagnostics "report"
        return "$rc"
    fi
}

main() {
    : > "$LOG"
    log "=== naive + naive_boost sweep starting (pid=$$) ==="
    preflight || exit 1

    # 1. Smoke test: cheap acme run validates the new naive_boost mode end-to-end.
    run_step naive_boost naive-boost acme || exit 1
    # 2. Proven chain — now the scotus legs (the known stall-risk spot).
    run_step naive       naive        scotus || exit 1
    run_step naive_boost naive-boost  scotus || exit 1

    run_judge  || exit 1
    run_report || exit 1

    log "=== DONE ==="
}

main "$@"
