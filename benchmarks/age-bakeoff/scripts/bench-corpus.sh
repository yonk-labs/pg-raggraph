#!/usr/bin/env bash
# bench-corpus.sh — canonical per-corpus sweep driver.
#
# For a single corpus CORPUS_ID, runs:
#   1. Corpus loader → produces (documents, questions) + writes question yaml
#   2. (Optional) 12-cell chunker × embedder factorial → pick winning cell
#   3. ExtractionOutput build via LLM (pgrg + AGE ingest path)
#   4. Mode × engine matrix sweep with winning chunker + embedder:
#        pgrg × {naive, naive_boost, local, global, hybrid, smart}
#        age  × {hybrid, local, global}
#        msgraph × {basic, local, global, drift}        (if ENABLE_MSGRAPH=1)
#   5. Judge all answers (majority-of-3)
#   6. Emit per-corpus paper stub at docs/benchmarks/<corpus_id>.md
#
# Env vars:
#   CORPUS_ID         — required. One of graphrag-bench-medical, graphrag-bench-novel,
#                       ms-hotpotqa, ms-kevin-scott, ms-msft-multi, ms-msft-single,
#                       pg-src, acme, scotus
#   N_QUESTIONS       — default 100 (stratified). Upstream corpus subset size.
#   SEED              — default 42. Applied to question sampling + any random step.
#   CHUNKER           — default auto (runs factorial to pick winner).
#                       Set to skip factorial and force a specific chunker.
#   EMBEDDER          — default auto. Same logic as CHUNKER.
#   ENABLE_MSGRAPH    — default 0. Set to 1 to include MS GraphRAG third engine.
#   SKIP_INGEST       — default 0. Set to 1 to reuse prior ingested corpus.
#   SKIP_FACTORIAL    — default 0. Skip step 2 (chunker × embedder sweep).
#   STEP_TIMEOUT_MIN  — default 45. Per-step timeout (matches run-mode-sweep.sh).
#   DRY_RUN           — default 0. Set to 1 to print planned steps without running.
#
# Usage:
#   CORPUS_ID=graphrag-bench-medical ./scripts/bench-corpus.sh
#   ENABLE_MSGRAPH=1 CORPUS_ID=ms-kevin-scott ./scripts/bench-corpus.sh
#
# Exit codes: 0 on success; non-zero on any failure (with diagnostics dumped).

set -u
set -o pipefail

: "${CORPUS_ID:?must set CORPUS_ID}"
N_QUESTIONS="${N_QUESTIONS:-100}"
SEED="${SEED:-42}"
CHUNKER="${CHUNKER:-auto}"
EMBEDDER="${EMBEDDER:-auto}"
ENABLE_MSGRAPH="${ENABLE_MSGRAPH:-0}"
SKIP_INGEST="${SKIP_INGEST:-0}"
SKIP_FACTORIAL="${SKIP_FACTORIAL:-0}"
STEP_TIMEOUT_MIN="${STEP_TIMEOUT_MIN:-45}"
DRY_RUN="${DRY_RUN:-0}"

BAKEOFF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$BAKEOFF_DIR/../.." && pwd)"
LOG_DIR="${BAKEOFF_DIR}/logs"
LOG="${LOG:-${LOG_DIR}/${CORPUS_ID}.log}"
mkdir -p "$LOG_DIR"

cd "$BAKEOFF_DIR"

# Load .env if present
if [ -f .env ]; then set -a; . .env; set +a; fi
# Propagate OPENAI_API_KEY → GRAPHRAG_API_KEY for MS GraphRAG subprocess use
export GRAPHRAG_API_KEY="${GRAPHRAG_API_KEY:-${OPENAI_API_KEY:-}}"

log()   { printf '[%s] %s\n' "$(date +'%H:%M:%S')" "$*" | tee -a "$LOG"; }
run()   { log "+ $*"; if [ "$DRY_RUN" = "1" ]; then return 0; fi; eval "$@"; }
die()   { log "FATAL: $*"; exit 1; }

log "==========================================================="
log "bench-corpus.sh: CORPUS_ID=$CORPUS_ID"
log "  N_QUESTIONS=$N_QUESTIONS SEED=$SEED"
log "  CHUNKER=$CHUNKER EMBEDDER=$EMBEDDER"
log "  ENABLE_MSGRAPH=$ENABLE_MSGRAPH"
log "  SKIP_INGEST=$SKIP_INGEST SKIP_FACTORIAL=$SKIP_FACTORIAL"
log "  DRY_RUN=$DRY_RUN"
log "==========================================================="

# ---------------------------------------------------------------------------
# Step 1. Ensure the question yaml exists (some corpora need generation)
# ---------------------------------------------------------------------------
Q_YAML="${BAKEOFF_DIR}/questions/${CORPUS_ID}.yaml"
if [ ! -f "$Q_YAML" ]; then
    log "Step 1: materialize question yaml for $CORPUS_ID"
    run "uv run python -m age_bakeoff.tools.materialize_questions \
        --corpus '$CORPUS_ID' \
        --n '$N_QUESTIONS' \
        --seed '$SEED' \
        --out '$Q_YAML'" \
      || die "question materialization failed"
else
    log "Step 1: question yaml already present at $Q_YAML"
fi

# ---------------------------------------------------------------------------
# Step 2. Chunker × embedder factorial (optional, ~2 hours on full 772-doc)
# ---------------------------------------------------------------------------
if [ "$SKIP_FACTORIAL" = "1" ]; then
    log "Step 2: SKIP_FACTORIAL=1, reusing CHUNKER=$CHUNKER EMBEDDER=$EMBEDDER"
elif [ "$CHUNKER" = "auto" ] || [ "$EMBEDDER" = "auto" ]; then
    log "Step 2: chunker × embedder factorial sweep"
    run "uv run python scripts/factorial-accuracy-runner.py \
        --corpus '$CORPUS_ID' \
        --precision int8 \
        --n-questions '$N_QUESTIONS' \
        --seed '$SEED'" \
      || die "factorial sweep failed"
    # Pick the winning cell
    WINNER_JSON="${BAKEOFF_DIR}/results/factorial-${CORPUS_ID}-winner.json"
    run "uv run python -m age_bakeoff.tools.pick_factorial_winner \
        --results 'results/factorial-accuracy-int8.json' \
        --corpus '$CORPUS_ID' \
        --out '$WINNER_JSON'" \
      || die "winner selection failed"
    # Read back winner
    if [ -f "$WINNER_JSON" ] && [ "$DRY_RUN" != "1" ]; then
        CHUNKER=$(jq -r '.chunker' "$WINNER_JSON")
        EMBEDDER=$(jq -r '.embedder' "$WINNER_JSON")
        log "  winner: chunker=$CHUNKER embedder=$EMBEDDER"
    fi
else
    log "Step 2: CHUNKER=$CHUNKER EMBEDDER=$EMBEDDER (skipping factorial)"
fi

# ---------------------------------------------------------------------------
# Step 3. Ingest (LLM extraction + chunk embedding for pgrg + AGE)
# ---------------------------------------------------------------------------
if [ "$SKIP_INGEST" = "1" ]; then
    log "Step 3: SKIP_INGEST=1, reusing existing ingested data"
else
    log "Step 3: ingest pgrg + AGE with chunker=$CHUNKER embedder=$EMBEDDER"
    export BAKEOFF_CHUNKER="$CHUNKER"
    export BAKEOFF_EMBEDDING_MODEL="$EMBEDDER"
    run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
        uv run age-bakeoff run --corpus '$CORPUS_ID' --mode hybrid --label base" \
      || die "ingest run failed"
fi

# ---------------------------------------------------------------------------
# Step 4. Mode × engine matrix sweep
# ---------------------------------------------------------------------------
log "Step 4: mode × engine matrix sweep"

# pgrg modes — each adds a new --label and reuses ingested data via --skip-ingest
for mode in naive naive_boost local global smart; do
    label="${mode}"
    log "  pgrg × $mode"
    run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
        uv run age-bakeoff run --corpus '$CORPUS_ID' \
        --mode '$mode' --label '$label' --skip-ingest" \
      || log "WARN: pgrg × $mode failed; continuing"
done

# AGE modes
for mode in local global; do
    label="age_${mode}"
    log "  age × $mode"
    run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
        uv run age-bakeoff run --corpus '$CORPUS_ID' \
        --mode '$mode' --label '$label' --skip-ingest --engine age" \
      || log "WARN: age × $mode failed; continuing"
done

# MS GraphRAG modes
if [ "$ENABLE_MSGRAPH" = "1" ]; then
    log "  msgraph: building index (one-time, ~minutes)"
    run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
        uv run python -m age_bakeoff.tools.msgraph_index \
        --corpus '$CORPUS_ID' --n '$N_QUESTIONS' --seed '$SEED'" \
      || die "msgraph index build failed"
    for mode in basic local global drift; do
        label="msgraph_${mode}"
        log "  msgraph × $mode"
        run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
            uv run python -m age_bakeoff.tools.msgraph_run \
            --corpus '$CORPUS_ID' --mode '$mode' --label '$label'" \
          || log "WARN: msgraph × $mode failed; continuing"
    done
fi

# ---------------------------------------------------------------------------
# Step 5. Judge majority-of-3 across all label files
# ---------------------------------------------------------------------------
log "Step 5: judge all labels for corpus $CORPUS_ID"
run "timeout --kill-after=30s ${STEP_TIMEOUT_MIN}m \
    uv run age-bakeoff judge --corpus '$CORPUS_ID'" \
  || die "judge failed"

# ---------------------------------------------------------------------------
# Step 6. Emit per-corpus paper stub
# ---------------------------------------------------------------------------
PAPER_PATH="${REPO_ROOT}/docs/benchmarks/${CORPUS_ID}.md"
log "Step 6: emit paper stub at $PAPER_PATH"
run "uv run python -m age_bakeoff.tools.emit_paper \
    --corpus '$CORPUS_ID' \
    --template '${REPO_ROOT}/docs/benchmarks/_template.md' \
    --out '$PAPER_PATH' \
    --chunker '$CHUNKER' --embedder '$EMBEDDER' \
    --enable-msgraph '$ENABLE_MSGRAPH'" \
  || die "paper emit failed"

log "==========================================================="
log "bench-corpus.sh: $CORPUS_ID done"
log "  paper: $PAPER_PATH"
log "  raw results: results/raw/${CORPUS_ID}*.json"
log "  judge results: results/judge/${CORPUS_ID}*.json"
log "==========================================================="
