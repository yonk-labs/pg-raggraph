#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo ">> Bringing up both DBs..."
docker compose up -d
sleep 3

echo ">> Fetching Postgres source slice..."
bash scripts/fetch_pg_src.sh

echo ">> Ingesting all corpora..."
uv run age-bakeoff ingest

echo ">> Running benchmark..."
uv run age-bakeoff run

echo ">> Running LLM judge..."
uv run age-bakeoff judge

echo ">> Generating report..."
uv run age-bakeoff report

echo ">> Done. See results/REPORT.md"
