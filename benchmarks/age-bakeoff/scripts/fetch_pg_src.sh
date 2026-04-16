#!/usr/bin/env bash
set -euo pipefail

CORPUS_DIR="$(cd "$(dirname "$0")/.." && pwd)/corpora/pg-src"
TAG="REL_16_5"

if [ -d "$CORPUS_DIR/.git" ]; then
    echo "Postgres source already fetched. Skipping."
    exit 0
fi

mkdir -p "$CORPUS_DIR"
git clone --depth 1 --branch "$TAG" https://github.com/postgres/postgres.git "$CORPUS_DIR"

cd "$CORPUS_DIR"
git sparse-checkout init --cone
git sparse-checkout set \
    src/backend/executor \
    src/backend/optimizer \
    src/include/executor \
    src/include/nodes \
    doc/src/sgml
echo "Postgres $TAG slice ready at $CORPUS_DIR"
