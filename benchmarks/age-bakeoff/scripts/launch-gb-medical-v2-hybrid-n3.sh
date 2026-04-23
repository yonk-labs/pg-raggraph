#!/usr/bin/env bash
# V2 medical hybrid re-run at n=3 (majority-of-3) to tighten the headline
# comparison. Only hybrid (pgrg + age) — other modes stay at n=1.
#
# Cost: ~$17 answers + ~$0.30 judge ≈ ~$17-18 on work_key.
# Wall: ~3-3.5 hours (AGE hybrid queries dominate at ~50s/call).

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
MASTER_LOG="${LOG_DIR}/gb-medical-v2-hybrid-n3.log"

log() {
    printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*" | tee -a "$MASTER_LOG"
}

log "=== v2 hybrid n=3 re-run start (work_key, gpt-5-mini) ==="

# The --label hybrid overwrites the existing v2 hybrid raw JSON (n=1, 200
# records) with the new n=3 output (600 records). Preserve a backup first.
cp -v results/raw/graphrag-bench-medical__hybrid.json \
   results/raw/graphrag-bench-medical__hybrid.v2_n1_backup.json 2>&1 | tee -a "$MASTER_LOG"
cp -v results/judge/graphrag-bench-medical__hybrid.json \
   results/judge/graphrag-bench-medical__hybrid.v2_n1_backup.json 2>&1 | tee -a "$MASTER_LOG"

log "=== hybrid -n 3 pgrg,age ==="
if timeout --kill-after=30s 300m \
     uv run age-bakeoff run \
     --corpus graphrag-bench-medical \
     --mode hybrid \
     --label hybrid \
     --skip-ingest \
     --engines pgrg,age \
     --budget-usd 50 \
     -n 3 \
     > "${LOG_DIR}/gb-medical-v2-hybrid-n3-run.log" 2>&1; then
    log "=== OK hybrid n=3 run ==="
else
    rc=$?
    log "=== FAIL hybrid n=3 run (exit $rc) ==="
    tail -20 "${LOG_DIR}/gb-medical-v2-hybrid-n3-run.log" | tee -a "$MASTER_LOG"
    exit $rc
fi

log "=== judging hybrid n=3 ==="
if uv run age-bakeoff judge \
     --corpus graphrag-bench-medical \
     --budget-usd 10 \
     > "${LOG_DIR}/gb-medical-v2-hybrid-n3-judge.log" 2>&1; then
    log "=== OK hybrid n=3 judge ==="
else
    rc=$?
    log "=== FAIL hybrid n=3 judge (exit $rc) ==="
    tail -20 "${LOG_DIR}/gb-medical-v2-hybrid-n3-judge.log" | tee -a "$MASTER_LOG"
    exit $rc
fi

log "=== DONE. Artifacts: ==="
ls -la results/raw/graphrag-bench-medical__hybrid*.json \
       results/judge/graphrag-bench-medical__hybrid*.json 2>&1 | tee -a "$MASTER_LOG"

log "=== v2 hybrid n=3 complete ==="
