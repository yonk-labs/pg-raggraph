#!/usr/bin/env bash
# V2 medical pgrg/naive_boost re-run at n=3. Tightens the "hybrid
# underperforms its own simpler modes" finding. pgrg-only, no AGE.
#
# Cost: ~$8.50 on work_key.
# Wall: ~50 min answers + ~30 min judge ≈ ~85 min total.

set -u
set -o pipefail

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BAKEOFF_DIR"
if [ -f .env ]; then set -a; . .env; set +a; fi

export BAKEOFF_ANSWER_BASE_URL=""
export BAKEOFF_ANSWER_MODEL=gpt-5-mini
export BAKEOFF_ANSWER_CHUNK_CHARS=0
export BAKEOFF_JUDGE_BASE_URL=""
export BAKEOFF_JUDGE_MODEL=gpt-5-mini
OPENAI_API_KEY="$(grep ^work_key= /home/yonk/yonk-tools/.openai | cut -d= -f2)"
export OPENAI_API_KEY
export GRAPHRAG_API_KEY="$OPENAI_API_KEY"

LOG_DIR="${BAKEOFF_DIR}/logs"
mkdir -p "$LOG_DIR"
MASTER_LOG="${LOG_DIR}/gb-medical-v2-naive_boost-n3.log"

log() {
    printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*" | tee -a "$MASTER_LOG"
}

log "=== v2 naive_boost n=3 re-run start (work_key, gpt-5-mini) ==="

cp -v results/raw/graphrag-bench-medical__naive_boost.json \
   results/raw/graphrag-bench-medical__naive_boost.v2_n1_backup.json 2>&1 | tee -a "$MASTER_LOG"
cp -v results/judge/graphrag-bench-medical__naive_boost.json \
   results/judge/graphrag-bench-medical__naive_boost.v2_n1_backup.json 2>&1 | tee -a "$MASTER_LOG"

log "=== naive_boost -n 3 pgrg-only ==="
if timeout --kill-after=30s 120m \
     uv run age-bakeoff run \
     --corpus graphrag-bench-medical \
     --mode naive_boost \
     --label naive_boost \
     --skip-ingest \
     --engines pgrg \
     --budget-usd 25 \
     -n 3 \
     > "${LOG_DIR}/gb-medical-v2-naive_boost-n3-run.log" 2>&1; then
    log "=== OK naive_boost n=3 run ==="
else
    rc=$?
    log "=== FAIL naive_boost n=3 run (exit $rc) ==="
    tail -20 "${LOG_DIR}/gb-medical-v2-naive_boost-n3-run.log" | tee -a "$MASTER_LOG"
    exit $rc
fi

log "=== judging naive_boost n=3 ==="
if uv run age-bakeoff judge \
     --corpus graphrag-bench-medical \
     --budget-usd 5 \
     > "${LOG_DIR}/gb-medical-v2-naive_boost-n3-judge.log" 2>&1; then
    log "=== OK naive_boost n=3 judge ==="
else
    rc=$?
    log "=== FAIL naive_boost n=3 judge (exit $rc) ==="
    tail -20 "${LOG_DIR}/gb-medical-v2-naive_boost-n3-judge.log" | tee -a "$MASTER_LOG"
    exit $rc
fi

log "=== DONE. Artifacts: ==="
ls -la results/raw/graphrag-bench-medical__naive_boost*.json \
       results/judge/graphrag-bench-medical__naive_boost*.json 2>&1 | tee -a "$MASTER_LOG"

log "=== v2 naive_boost n=3 complete ==="
