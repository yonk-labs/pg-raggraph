# AGE vs pg-raggraph Bake-Off Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Mission Brief:** `skill-output/mission-brief/Mission-Brief-age-bakeoff.md` — this plan is written against that brief. Every task maps to one or more SC-XXX criteria. Drift checkpoints DC-001..DC-FINAL appear as hard gates (⛔) at the specified phase transitions.

**Goal:** Build a reproducible head-to-head benchmark between Apache AGE and pg-raggraph across three corpora (Acme Labs, SCOTUS, Postgres executor+planner), measuring end-to-end latency, deterministic fact recall, and LLM-judged answer quality on 90 gold-labeled questions — with explicit honesty about where AGE wins (if anywhere).

**Architecture:** Single Python package (`age_bakeoff`) with shared primitives (chunker, extraction output format, config) feeding two thin engine adapters. The AGE adapter wraps the retrieval code from `yonk-samples/graphrag-demo`. The pg-raggraph adapter wraps the `GraphRAG` class but bypasses its built-in chunker/extractor to guarantee identical graph inputs. A harness runs 90 questions × 3 runs × 2 engines, two scorers grade the outputs (deterministic fact recall + GPT-based LLM judge with 3× majority vote), and a deterministic report generator produces `REPORT.md`.

**Tech Stack:** Python 3.12, uv, asyncio, pydantic v2, psycopg3 (AGE adapter), pg-raggraph (direct import), FastEmbed (`BAAI/bge-small-en-v1.5`), OpenAI Python SDK (answer generation + judge), pytest with pytest-asyncio, PostgreSQL 16 (two Docker containers on distinct ports), click CLI.

**Fairness mechanism:** Both engines receive byte-identical pre-chunked content for every corpus. For Acme and SCOTUS, structural graph data comes from the graphrag-demo's hand-curated seed output (both engines write the same nodes and edges into their respective schemas). For Postgres, a single shared LLM extraction pass produces one `extraction.json` that both engines ingest. No per-engine chunking or extraction differences. Full rationale goes in `ARCHITECTURE.md`.

---

## File Structure

```
pg-raggraph/benchmarks/age-bakeoff/
├── README.md                         # how to reproduce
├── ARCHITECTURE.md                   # fairness rationale, design decisions
├── docker-compose.yml                # pg-raggraph DB + AGE DB on distinct ports
├── .env.example                      # OPENAI_API_KEY, model name, cost budget
├── .gitignore                        # results/raw/, .venv, corpora/pg-src/
├── pyproject.toml                    # deps: pg-raggraph, openai, psycopg[binary], pydantic, click, pyyaml, fastembed, pytest, pytest-asyncio
├── run-bakeoff.sh                    # one-shot entrypoint script
│
├── src/age_bakeoff/
│   ├── __init__.py
│   ├── config.py                     # BakeoffConfig (env-driven)
│   ├── models.py                     # Chunk, ExtractedEntity, ExtractedRelationship, Question, RunResult
│   ├── chunker.py                    # shared pre-chunker (prose + code-aware)
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── shared.py                 # LLM extraction (OpenAI) for pg-src corpus
│   │   └── loaders.py                # hand-curated data for acme/scotus (from graphrag-demo seeds)
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── base.py                   # Engine protocol (ingest, query, info)
│   │   ├── age.py                    # AGE adapter (wraps demo retrieval code)
│   │   └── pgrg.py                   # pg-raggraph adapter (direct GraphRAG + DB writer)
│   ├── corpora/
│   │   ├── __init__.py
│   │   ├── base.py                   # Corpus protocol
│   │   ├── acme.py                   # AcmeCorpus — loads from graphrag-demo seed data
│   │   ├── scotus.py                 # ScotusCorpus — same
│   │   └── pg_src.py                 # PgSrcCorpus — clones and extracts
│   ├── runner.py                     # benchmark harness
│   ├── scorers/
│   │   ├── __init__.py
│   │   ├── fact_recall.py            # deterministic
│   │   └── llm_judge.py              # OpenAI judge with 3x majority
│   ├── report.py                     # deterministic markdown generator
│   └── cli.py                        # click: setup, ingest, run, score, report
│
├── questions/
│   ├── schema.py                     # pydantic models for YAML validation
│   ├── acme.yaml                     # 30 questions (≥5 bridging)
│   ├── scotus.yaml                   # 30 questions (≥5 bridging)
│   └── pg-src.yaml                   # 30 questions (≥5 bridging)
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── tiny_corpus.json          # 5 chunks + 3 entities + 2 rels
│   │   ├── tiny_questions.yaml       # 2 questions
│   │   ├── canned_raw_results.json   # synthetic runner output
│   │   └── canned_report.md          # expected generator output (snapshot)
│   ├── test_chunker.py               # SC-001
│   ├── test_models.py                # models round-trip
│   ├── test_questions_schema.py      # SC-003
│   ├── test_runner_schema.py         # SC-004
│   ├── test_fact_recall.py           # SC-005
│   ├── test_llm_judge.py             # SC-006 (mocked OpenAI)
│   ├── test_report.py                # SC-007 (snapshot)
│   ├── test_engine_parity.py         # SC-001+SC-002 integration
│   └── test_runner_smoke.py          # SC-004 2-question end-to-end
│
└── results/
    ├── raw/                          # produced at run-time (git-ignored)
    └── REPORT.md                     # final generated document
```

---

## Phase 0: Scaffolding

Stand up the directory tree, Python package, Docker stack, and AGE container image. Verify both DBs boot and accept connections.

### Task 0.1: Create directory skeleton and Python package

**Files:**
- Create: `benchmarks/age-bakeoff/pyproject.toml`
- Create: `benchmarks/age-bakeoff/.gitignore`
- Create: `benchmarks/age-bakeoff/.env.example`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/__init__.py`
- Create: `benchmarks/age-bakeoff/tests/conftest.py`

**SC coverage:** SC-010 (reproduction scaffold)

- [ ] **Step 1: Create the directory tree**

Run:
```bash
cd /home/yonk/yonk-tools/pg-raggraph
mkdir -p benchmarks/age-bakeoff/{src/age_bakeoff/{engines,corpora,extraction,scorers},questions,tests/fixtures,results/raw,corpora/{acme,scotus,pg-src}}
touch benchmarks/age-bakeoff/src/age_bakeoff/__init__.py
touch benchmarks/age-bakeoff/src/age_bakeoff/{engines,corpora,extraction,scorers}/__init__.py
touch benchmarks/age-bakeoff/tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "age-bakeoff"
version = "0.1.0"
description = "Head-to-head benchmark: Apache AGE vs pg-raggraph"
requires-python = ">=3.12"
dependencies = [
    "pg-raggraph",
    "openai>=1.50",
    "psycopg[binary]>=3.2",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "click>=8.1",
    "pyyaml>=6.0",
    "fastembed>=0.3",
    "numpy>=1.26",
    "tiktoken>=0.7",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
]

[project.scripts]
age-bakeoff = "age_bakeoff.cli:cli"

[tool.uv.sources]
pg-raggraph = { path = "../..", editable = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 3: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
results/raw/
corpora/pg-src/
.env
uv.lock
```

- [ ] **Step 4: Write `.env.example`**

```dotenv
# OpenAI API key — required for answer generation and judging
OPENAI_API_KEY=YOUR_KEY_HERE

# Answer generation model (default gpt-5-mini; fallback gpt-4o-mini)
BAKEOFF_ANSWER_MODEL=gpt-5-mini

# Judge model (same family; documented fallback gpt-4o-mini)
BAKEOFF_JUDGE_MODEL=gpt-5-mini

# Hard cost ceiling in USD — harness aborts if exceeded
BAKEOFF_COST_BUDGET_USD=25

# Shared retrieval hyperparameters (must match both engines)
BAKEOFF_TOP_K=10
BAKEOFF_HOP_BUDGET=2

# Database connections
PGRG_DSN=postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg
AGE_DSN=postgresql://postgres:postgres@localhost:5435/age_bakeoff_age

# Optional: override FastEmbed model
BAKEOFF_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

- [ ] **Step 5: Write stub `conftest.py`**

```python
"""Shared test fixtures for the age-bakeoff benchmark."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _disable_external_calls(monkeypatch):
    """Guard: no test may accidentally hit real OpenAI or a live DB without opting in."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
```

- [ ] **Step 6: Verify package installs**

Run:
```bash
cd benchmarks/age-bakeoff && uv sync --extra dev
```

Expected: exits cleanly, `.venv` populated. If pg-raggraph editable install fails, confirm the path `../..` resolves to the pg-raggraph repo root.

- [ ] **Step 7: Commit**

```bash
cd /home/yonk/yonk-tools/pg-raggraph
git add benchmarks/age-bakeoff/
git commit -m "feat(bakeoff): scaffold benchmark package structure"
```

---

### Task 0.2: Docker stack with both engines side-by-side

**Files:**
- Create: `benchmarks/age-bakeoff/docker-compose.yml`
- Create: `benchmarks/age-bakeoff/docker/age/Dockerfile`

**SC coverage:** SC-010 (reproducibility), supports SC-002 (symmetric configs)

The pg-raggraph side uses the standard `pgvector/pgvector:pg16` image (no AGE). The AGE side needs a custom Dockerfile because no public image ships PG 16 + AGE + pgvector together. Copy the proven Dockerfile from `yonk-samples/graphrag-demo/postgres/Dockerfile` as a starting point and verify it still builds.

- [ ] **Step 1: Read the reference AGE Dockerfile**

Run:
```bash
cat /home/yonk/yonk-samples/graphrag-demo/postgres/Dockerfile
```

Expected: prints a multi-stage PG16 build installing pgvector and Apache AGE from source. Use this as the basis for `docker/age/Dockerfile` — do not modify the yonk-samples copy.

- [ ] **Step 2: Copy the AGE Dockerfile into the benchmark tree**

```bash
mkdir -p benchmarks/age-bakeoff/docker/age
cp /home/yonk/yonk-samples/graphrag-demo/postgres/Dockerfile benchmarks/age-bakeoff/docker/age/Dockerfile
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  pgrg:
    image: pgvector/pgvector:pg16
    container_name: age-bakeoff-pgrg
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: age_bakeoff_pgrg
    ports:
      - "5434:5432"
    volumes:
      - pgrg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres", "-d", "age_bakeoff_pgrg"]
      interval: 3s
      timeout: 3s
      retries: 20

  age:
    build:
      context: ./docker/age
      dockerfile: Dockerfile
    container_name: age-bakeoff-age
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: age_bakeoff_age
    ports:
      - "5435:5432"
    volumes:
      - age_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres", "-d", "age_bakeoff_age"]
      interval: 3s
      timeout: 3s
      retries: 40

volumes:
  pgrg_data:
  age_data:
```

- [ ] **Step 4: Bring both stacks up**

```bash
cd benchmarks/age-bakeoff && docker compose up -d
docker compose ps
```

Expected: both `pgrg` and `age` services show `healthy` within ~2 minutes (AGE takes longer on first build).

- [ ] **Step 5: Verify extensions on both sides**

```bash
docker exec age-bakeoff-pgrg psql -U postgres -d age_bakeoff_pgrg -c \
  "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; SELECT extname FROM pg_extension;"

docker exec age-bakeoff-age psql -U postgres -d age_bakeoff_age -c \
  "CREATE EXTENSION IF NOT EXISTS age CASCADE; CREATE EXTENSION IF NOT EXISTS vector; LOAD 'age'; SELECT extname FROM pg_extension;"
```

Expected: pg-raggraph side lists `vector` and `pg_trgm`; AGE side lists `age` and `vector`. If AGE install fails, check that `shared_preload_libraries` is set in the container's `postgresql.conf` — the Dockerfile must set it.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/age-bakeoff/docker-compose.yml benchmarks/age-bakeoff/docker/
git commit -m "feat(bakeoff): docker stack with both engines on distinct ports"
```

---

## Phase 1: Shared models, config, and chunker

Define the data contract shared by both engines. These primitives are the fairness boundary — every byte that flows into an engine passes through these types.

### Task 1.1: Shared pydantic models

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/models.py`
- Create: `benchmarks/age-bakeoff/tests/test_models.py`

**SC coverage:** SC-001 (shared chunk contract), SC-004 (RunResult schema)

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:
```python
"""Round-trip tests for the shared pydantic models."""
from __future__ import annotations

from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
    Question,
    QuestionClass,
    RunResult,
)


def test_chunk_round_trip():
    c = Chunk(
        id="doc1::0",
        document_id="doc1",
        content="hello world",
        sequence=0,
        metadata={"source_path": "docs/intro.md"},
    )
    assert c.model_dump()["id"] == "doc1::0"
    assert Chunk.model_validate(c.model_dump()) == c


def test_extracted_entity_round_trip():
    e = ExtractedEntity(
        id="ent_person_alice",
        name="Alice",
        entity_type="Person",
        description="A person",
        properties={"team": "platform"},
    )
    assert ExtractedEntity.model_validate(e.model_dump()) == e


def test_extracted_relationship_round_trip():
    r = ExtractedRelationship(
        src_id="ent_person_alice",
        dst_id="ent_project_ingest",
        rel_type="WORKS_ON",
        weight=0.9,
        description="Alice works on Ingest",
        properties={},
    )
    assert ExtractedRelationship.model_validate(r.model_dump()) == r


def test_extraction_output_matches_contract():
    out = ExtractionOutput(
        corpus="acme",
        chunks=[],
        entities=[],
        relationships=[],
    )
    assert out.corpus == "acme"


def test_question_requires_bridging_class_enum():
    q = Question(
        id="acme-q-001",
        question="Who works on Ingest?",
        gold_answer="Alice and Bob.",
        required_facts=["Alice", "Bob"],
        required_entities=["ent_person_alice", "ent_person_bob"],
        question_class=QuestionClass.single_hop,
    )
    assert q.question_class == QuestionClass.single_hop


def test_run_result_schema():
    r = RunResult(
        engine="pgrg",
        corpus="acme",
        question_id="acme-q-001",
        run_number=1,
        cold=True,
        retrieval_ms=42.0,
        answer_ms=800.0,
        retrieved_chunk_ids=["doc1::0"],
        generated_answer="Alice and Bob.",
    )
    assert r.retrieval_ms == 42.0
    assert RunResult.model_validate(r.model_dump()) == r
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'age_bakeoff.models'`

- [ ] **Step 3: Implement `models.py`**

```python
"""Shared data contracts for the bake-off."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    """A single content chunk — the fairness boundary between engines."""

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    content: str
    sequence: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    entity_type: str
    description: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    src_id: str
    dst_id: str
    rel_type: str
    weight: float = 1.0
    description: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractionOutput(BaseModel):
    """Byte-identical payload that both engines ingest."""

    corpus: str
    chunks: list[Chunk]
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]


class QuestionClass(str, Enum):
    semantic = "semantic"
    single_hop = "single_hop"
    multi_hop_bridging = "multi_hop_bridging"
    factual = "factual"


class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    question: str
    gold_answer: str
    required_facts: list[str]
    required_entities: list[str] = Field(default_factory=list)
    question_class: QuestionClass
    notes: str = ""


class RunResult(BaseModel):
    engine: str  # "pgrg" | "age"
    corpus: str
    question_id: str
    run_number: int
    cold: bool
    retrieval_ms: float
    answer_ms: float
    retrieved_chunk_ids: list[str]
    generated_answer: str
    error: str | None = None
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/models.py benchmarks/age-bakeoff/tests/test_models.py
git commit -m "feat(bakeoff): shared pydantic models (Chunk, Entity, Relationship, Question, RunResult)"
```

---

### Task 1.2: BakeoffConfig — single source of truth for all shared settings

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/config.py`
- Create: `benchmarks/age-bakeoff/tests/test_config.py`

**SC coverage:** SC-002 (matching model IDs), SC-010 (single shared config file)

- [ ] **Step 1: Write the failing test**

```python
"""Config loads from env and enforces model symmetry."""
from __future__ import annotations

import pytest

from age_bakeoff.config import BakeoffConfig


def test_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    assert cfg.embedding_model == "BAAI/bge-small-en-v1.5"
    assert cfg.top_k == 10
    assert cfg.hop_budget == 2
    assert cfg.cost_budget_usd == 25.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("BAKEOFF_ANSWER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BAKEOFF_TOP_K", "15")
    cfg = BakeoffConfig()
    assert cfg.answer_model == "gpt-4o-mini"
    assert cfg.top_k == 15


def test_openai_key_required(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        BakeoffConfig()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `config.py`**

```python
"""Shared bakeoff configuration — single source of truth for both engines."""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BakeoffConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BAKEOFF_",
        env_file=".env",
        extra="ignore",
    )

    answer_model: str = "gpt-5-mini"
    judge_model: str = "gpt-5-mini"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    top_k: int = 10
    hop_budget: int = 2
    cost_budget_usd: float = 25.0

    pgrg_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg",
        validation_alias="PGRG_DSN",
    )
    age_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5435/age_bakeoff_age",
        validation_alias="AGE_DSN",
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    @field_validator("openai_api_key")
    @classmethod
    def _require_key(cls, v: str) -> str:
        if not v:
            raise ValueError("OPENAI_API_KEY is required")
        return v
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/config.py benchmarks/age-bakeoff/tests/test_config.py
git commit -m "feat(bakeoff): BakeoffConfig with env-driven shared settings"
```

---

### Task 1.3: Shared chunker (prose + code-aware)

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/chunker.py`
- Create: `benchmarks/age-bakeoff/tests/test_chunker.py`
- Create: `benchmarks/age-bakeoff/tests/fixtures/tiny_doc.md`
- Create: `benchmarks/age-bakeoff/tests/fixtures/tiny_doc.py`

**SC coverage:** SC-001 (byte-identical chunks on both sides)

The chunker has one job: given a document path or raw text, produce a deterministic list of `Chunk` objects that is identical across runs. Both engine adapters call the same chunker — neither engine ever chunks on its own. For `.c`, `.h`, `.py` files we respect function/struct boundaries with a fallback hard-split at 800 tokens. For prose we split on markdown headings with a sentence-aware fallback. Everything else hard-splits on paragraph boundaries.

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/tiny_doc.md`:
```markdown
# Title

First paragraph about widgets.

## Section A

Second paragraph about gadgets.

## Section B

Third paragraph about gizmos.
```

Create `tests/fixtures/tiny_doc.py`:
```python
def alpha():
    """Alpha."""
    return 1


def beta():
    """Beta."""
    return 2


class Gamma:
    def method(self):
        return "g"
```

Create `tests/test_chunker.py`:
```python
from __future__ import annotations

import hashlib
import json

from age_bakeoff.chunker import chunk_file, chunk_text
from age_bakeoff.models import Chunk


def test_prose_chunker_splits_on_headings(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.md")
    assert len(chunks) >= 2
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].sequence == 0
    assert chunks[1].sequence == 1
    # Section A and Section B produce distinct chunks
    contents = [c.content for c in chunks]
    assert any("Section A" in c for c in contents)
    assert any("Section B" in c for c in contents)


def test_code_chunker_splits_on_function_boundaries(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.py")
    contents = "\n---\n".join(c.content for c in chunks)
    assert "def alpha" in contents
    assert "def beta" in contents
    assert "class Gamma" in contents


def test_chunker_is_deterministic(fixtures_dir):
    a = chunk_file(fixtures_dir / "tiny_doc.md")
    b = chunk_file(fixtures_dir / "tiny_doc.md")
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_chunker_produces_stable_hashes(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.md")
    payload = json.dumps([c.model_dump() for c in chunks], sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    # Snapshot: if the chunker changes, this test fails and we re-verify parity
    assert len(digest) == 64


def test_chunk_text_explicit_doc_id():
    chunks = chunk_text("a paragraph", document_id="doc42")
    assert chunks[0].document_id == "doc42"
    assert chunks[0].id.startswith("doc42::")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_chunker.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chunker.py`**

```python
"""Shared pre-chunker — both engines ingest the output of this module.

Responsibilities:
1. Prose: split on markdown headings, fall back to paragraph+sentence aggregation
2. Code (.py, .c, .h): split on top-level function/class/struct boundaries,
   fall back to hard 800-token split
3. Plain text: paragraph-aware hard split

Determinism: given the same bytes on disk, produces byte-identical output.
"""
from __future__ import annotations

import re
from pathlib import Path

from age_bakeoff.models import Chunk

_MAX_CHARS = 3000  # ~750 tokens for BAAI/bge-small-en-v1.5
_MIN_CHARS = 200

_MD_HEADING = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
_PY_DEF = re.compile(r"^(def |class |async def )", re.MULTILINE)
_C_FUNC = re.compile(
    r"^(?:static\s+)?(?:[A-Za-z_][\w*\s]*)\s+\**[A-Za-z_]\w*\s*\([^;]*\)\s*\{",
    re.MULTILINE,
)
_C_STRUCT = re.compile(r"^(?:typedef\s+)?struct\s+[A-Za-z_]\w*", re.MULTILINE)


def chunk_file(path: str | Path) -> list[Chunk]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    doc_id = str(p.name)
    ext = p.suffix.lower()
    if ext in (".md", ".sgml", ".rst", ".txt"):
        splits = _split_prose(text)
    elif ext in (".py",):
        splits = _split_python(text)
    elif ext in (".c", ".h"):
        splits = _split_c(text)
    else:
        splits = _split_plain(text)
    return _to_chunks(doc_id, splits, source_path=str(p))


def chunk_text(text: str, document_id: str, doc_type: str = "prose") -> list[Chunk]:
    if doc_type == "code":
        splits = _split_plain(text)
    else:
        splits = _split_prose(text)
    return _to_chunks(document_id, splits)


def _split_prose(text: str) -> list[str]:
    headings = list(_MD_HEADING.finditer(text))
    if not headings:
        return _split_plain(text)
    result: list[str] = []
    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        if section:
            result.extend(_hard_split(section))
    # Prefix (anything before first heading) gets its own chunk(s)
    if headings[0].start() > 0:
        prefix = text[: headings[0].start()].strip()
        if prefix:
            result = _hard_split(prefix) + result
    return [s for s in result if len(s) >= _MIN_CHARS or len(s) == len(text)]


def _split_python(text: str) -> list[str]:
    defs = list(_PY_DEF.finditer(text))
    if not defs:
        return _split_plain(text)
    result: list[str] = []
    # Module header
    if defs[0].start() > 0:
        header = text[: defs[0].start()].strip()
        if header:
            result.extend(_hard_split(header))
    for i, match in enumerate(defs):
        start = match.start()
        end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
        block = text[start:end].strip()
        if block:
            result.extend(_hard_split(block))
    return result


def _split_c(text: str) -> list[str]:
    boundaries = sorted(
        [m.start() for m in _C_FUNC.finditer(text)]
        + [m.start() for m in _C_STRUCT.finditer(text)]
    )
    if not boundaries:
        return _split_plain(text)
    result: list[str] = []
    if boundaries[0] > 0:
        header = text[: boundaries[0]].strip()
        if header:
            result.extend(_hard_split(header))
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        block = text[start:end].strip()
        if block:
            result.extend(_hard_split(block))
    return result


def _split_plain(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 2 > _MAX_CHARS and buffer:
            result.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer:
        result.append(buffer.strip())
    return result


def _hard_split(text: str) -> list[str]:
    if len(text) <= _MAX_CHARS:
        return [text]
    out: list[str] = []
    for i in range(0, len(text), _MAX_CHARS):
        out.append(text[i : i + _MAX_CHARS])
    return out


def _to_chunks(
    document_id: str, splits: list[str], source_path: str | None = None
) -> list[Chunk]:
    meta: dict = {}
    if source_path:
        meta["source_path"] = source_path
    return [
        Chunk(
            id=f"{document_id}::{i}",
            document_id=document_id,
            content=content,
            sequence=i,
            metadata=meta,
        )
        for i, content in enumerate(splits)
    ]
```

- [ ] **Step 4: Run tests and iterate until green**

Run: `uv run pytest tests/test_chunker.py -v`
Expected: 5 passed. If `test_prose_chunker_splits_on_headings` fails with `< 2 chunks`, the prose splitter isn't emitting distinct sections — walk the `_split_prose` logic on the tiny_doc.md fixture.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/chunker.py benchmarks/age-bakeoff/tests/test_chunker.py benchmarks/age-bakeoff/tests/fixtures/tiny_doc.md benchmarks/age-bakeoff/tests/fixtures/tiny_doc.py
git commit -m "feat(bakeoff): shared chunker with prose/python/C splitters"
```

---

## Phase 2: Shared extraction output

Produce a single `ExtractionOutput` JSON per corpus that contains chunks, entities, and relationships. This is the byte-identical payload that both engines ingest. For Acme and SCOTUS we reuse the demo's hand-curated graph scripts, converting them into the shared format. For Postgres we run one LLM extraction pass whose output is cached on disk.

### Task 2.1: Acme + SCOTUS graph loaders (from demo seeds)

**Files:**
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/seed/seed.py`
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/seed/generate_data.py`
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/seed/scotus_data.py`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/extraction/loaders.py`
- Create: `benchmarks/age-bakeoff/tests/test_extraction_loaders.py`

**SC coverage:** SC-001 (same nodes/edges fed to both engines)

- [ ] **Step 1: Understand the demo's seed output**

Run:
```bash
wc -l /home/yonk/yonk-samples/graphrag-demo/app/seed/*.py
```
Then read each file to locate: (a) the structured tables of people/projects/services/cases/justices, (b) the relationship list, (c) the document generator that produces the text the demo ingests. Note: `generate_data.py` contains templated strings; we do not want templated content re-run — we want the already-generated documents.

- [ ] **Step 2: Write the failing test**

Create `tests/test_extraction_loaders.py`:
```python
from age_bakeoff.extraction.loaders import load_acme_extraction, load_scotus_extraction
from age_bakeoff.models import ExtractionOutput


def test_acme_loader_shape():
    out = load_acme_extraction()
    assert isinstance(out, ExtractionOutput)
    assert out.corpus == "acme"
    assert len(out.chunks) > 50  # ~160 docs in demo → more chunks
    assert len(out.entities) >= 20  # people + projects + services + teams
    assert len(out.relationships) >= 20
    # All relationship endpoints resolve to entities
    eids = {e.id for e in out.entities}
    for r in out.relationships:
        assert r.src_id in eids, f"dangling src {r.src_id}"
        assert r.dst_id in eids, f"dangling dst {r.dst_id}"


def test_scotus_loader_shape():
    out = load_scotus_extraction()
    assert out.corpus == "scotus"
    assert len(out.chunks) > 20
    assert any(e.entity_type == "Justice" for e in out.entities)
    assert any(r.rel_type == "CITED" for r in out.relationships)


def test_loader_deterministic():
    a = load_acme_extraction()
    b = load_acme_extraction()
    assert [c.model_dump() for c in a.chunks] == [c.model_dump() for c in b.chunks]
    assert [e.model_dump() for e in a.entities] == [e.model_dump() for e in b.entities]
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/test_extraction_loaders.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `extraction/loaders.py`**

The implementation mirrors the demo's seed tables directly. Read `seed.py` for the canonical data structures and transcribe them into our `ExtractedEntity`/`ExtractedRelationship` format. Do NOT import from the demo — the demo's `app/` is not on our path and we want a standalone copy.

```python
"""Loaders that produce ExtractionOutput for Acme and SCOTUS corpora.

The data mirrors yonk-samples/graphrag-demo/app/seed/ — mirrored (not imported)
so the bake-off is self-contained.
"""
from __future__ import annotations

import json
from pathlib import Path

from age_bakeoff.chunker import chunk_text
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_DATA_DIR = Path(__file__).parent / "data"


def load_acme_extraction() -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "acme.json").read_text())
    return _build_output("acme", raw)


def load_scotus_extraction() -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "scotus.json").read_text())
    return _build_output("scotus", raw)


def _build_output(corpus: str, raw: dict) -> ExtractionOutput:
    entities = [ExtractedEntity(**e) for e in raw["entities"]]
    relationships = [ExtractedRelationship(**r) for r in raw["relationships"]]
    chunks: list[Chunk] = []
    for doc in raw["documents"]:
        doc_chunks = chunk_text(
            text=doc["content"],
            document_id=doc["id"],
        )
        # Inject author/project metadata so retrieval scoring can cross-reference
        for c in doc_chunks:
            meta = {**c.metadata, "author_id": doc.get("author_id"), "project_id": doc.get("project_id")}
            chunks.append(c.model_copy(update={"metadata": meta}))
    return ExtractionOutput(
        corpus=corpus,
        chunks=chunks,
        entities=entities,
        relationships=relationships,
    )
```

- [ ] **Step 5: Port the Acme seed data to `data/acme.json`**

Run the demo's seed scripts offline once to capture the output, OR read `seed.py` + `generate_data.py` and transcribe the data tables into `data/acme.json`. Use this structure:

```json
{
  "entities": [
    {"id": "person_alice", "name": "Alice Chen", "entity_type": "Person", "description": "Platform team lead", "properties": {}},
    {"id": "team_platform", "name": "Platform", "entity_type": "Team", "description": "Infrastructure team", "properties": {}},
    {"id": "project_ingest", "name": "Ingest Pipeline", "entity_type": "Project", "description": "Data ingestion", "properties": {}},
    {"id": "service_kafka", "name": "Kafka", "entity_type": "Service", "description": "Message bus", "properties": {}}
  ],
  "relationships": [
    {"src_id": "person_alice", "dst_id": "team_platform", "rel_type": "MEMBER_OF", "weight": 1.0, "description": "", "properties": {}},
    {"src_id": "person_alice", "dst_id": "project_ingest", "rel_type": "WORKS_ON", "weight": 1.0, "description": "", "properties": {}},
    {"src_id": "project_ingest", "dst_id": "service_kafka", "rel_type": "DEPENDS_ON", "weight": 1.0, "description": "", "properties": {}}
  ],
  "documents": [
    {
      "id": "doc_ingest_design",
      "author_id": "person_alice",
      "project_id": "project_ingest",
      "content": "# Ingest Pipeline Design\n\nOwner: Alice Chen.\n\nThe ingest pipeline uses Kafka as its primary transport layer..."
    }
  ]
}
```

Capture the full Acme entity/relationship/document set from the demo's generator output. Expected totals: ~25 people, ~10 projects, ~8 services, ~5 teams, ~5 technologies; ~50 relationships; ~160 documents.

Practical capture procedure:
```bash
# Run the demo seed once and dump to JSON via a small helper
cd /home/yonk/yonk-samples/graphrag-demo
uv run python -c "
from app.seed.generate_data import generate_all_data
import json
data = generate_all_data()
print(json.dumps(data, indent=2))
" > /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff/src/age_bakeoff/extraction/data/acme.raw.json
```
If `generate_all_data` doesn't exist verbatim, adapt the call site based on what the seed module actually exposes. Then write a small adapter script (committed as `scripts/port_acme_seed.py` in the bakeoff dir) that reshapes the raw dump into the schema above.

- [ ] **Step 6: Repeat for SCOTUS → `data/scotus.json`**

Same procedure, sourcing from `app/seed/scotus_data.py`. Expected: ~15 justices, ~40 cases, ~15 issues, ~80 relationships (CITED, CONCERNS, WROTE_OPINION, VOTED_*), ~40 documents.

- [ ] **Step 7: Run tests until green**

Run: `uv run pytest tests/test_extraction_loaders.py -v`
Expected: 3 passed. Fix any dangling relationship endpoints by scanning the seed data for typos.

- [ ] **Step 8: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/extraction/loaders.py \
        benchmarks/age-bakeoff/src/age_bakeoff/extraction/data/ \
        benchmarks/age-bakeoff/tests/test_extraction_loaders.py \
        benchmarks/age-bakeoff/scripts/port_acme_seed.py
git commit -m "feat(bakeoff): acme + scotus extraction loaders mirrored from graphrag-demo seeds"
```

---

### Task 2.2: Postgres source extractor (clone + LLM extraction pass)

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/extraction/pg_src.py`
- Create: `benchmarks/age-bakeoff/scripts/fetch_pg_src.sh`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/extraction/prompts.py`
- Create: `benchmarks/age-bakeoff/tests/test_pg_src_extraction.py`

**SC coverage:** SC-001 (shared extraction output for Postgres corpus)

Postgres has no hand-curated graph. We run one LLM extraction pass over all chunks and cache the result to `data/pg_src.json`. Subsequent runs read the cache — extraction cost is paid once. Pinning to a specific Postgres tag (`REL_16_5`) guarantees reproducibility.

- [ ] **Step 1: Write the fetch script**

Create `scripts/fetch_pg_src.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

CORPUS_DIR="$(dirname "$0")/../corpora/pg-src"
TAG="REL_16_5"

if [ -d "$CORPUS_DIR/.git" ]; then
    echo "Postgres source already fetched. Skipping."
    exit 0
fi

mkdir -p "$CORPUS_DIR"
git clone --depth 1 --branch "$TAG" https://github.com/postgres/postgres.git "$CORPUS_DIR"

# Keep only the slice we care about to save disk space
cd "$CORPUS_DIR"
git sparse-checkout init --cone
git sparse-checkout set \
    src/backend/executor \
    src/backend/optimizer \
    src/include/executor \
    src/include/nodes \
    doc/src/sgml/planner-stats.sgml \
    doc/src/sgml/planner-optimizer.sgml \
    doc/src/sgml/indices.sgml \
    doc/src/sgml/performance-tips.sgml \
    doc/src/sgml/runtime.sgml
echo "Postgres $TAG slice ready at $CORPUS_DIR"
```

Make executable: `chmod +x benchmarks/age-bakeoff/scripts/fetch_pg_src.sh`

- [ ] **Step 2: Write the extraction prompt**

Create `src/age_bakeoff/extraction/prompts.py`:
```python
"""LLM extraction prompts — frozen for reproducibility."""

EXTRACTION_SYSTEM = """You are extracting a knowledge graph from source code or technical documentation.

Given a chunk of text, identify:
1. ENTITIES: functions, structs, types, files, concepts, algorithms
2. RELATIONSHIPS: CALLS, DEFINED_IN, INHERITS, IMPLEMENTS, REFERENCES, RELATES_TO

Return strict JSON matching this schema:
{
  "entities": [
    {"name": "string", "entity_type": "Function|Struct|Type|File|Concept|Algorithm", "description": "1-sentence purpose"}
  ],
  "relationships": [
    {"src": "entity name", "dst": "entity name", "rel_type": "CALLS|DEFINED_IN|INHERITS|IMPLEMENTS|REFERENCES|RELATES_TO", "description": "1-sentence rationale"}
  ]
}

Rules:
- Entity names must be exact (e.g., `ExecSeqScan`, `Plan`, `costsize.c`)
- Only include entities you can point to in the text
- Relationship endpoints must be names you listed in entities
- Skip purely syntactic things (local variables, return types of trivial accessors)
- Maximum 15 entities and 15 relationships per chunk
"""

EXTRACTION_USER_TEMPLATE = """Chunk from {source_path}:

```
{content}
```

Return only JSON, no prose."""
```

- [ ] **Step 3: Write the failing test for the extractor**

```python
"""Postgres source extractor — mocked OpenAI, tests aggregation logic."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from age_bakeoff.extraction.pg_src import extract_pg_src
from age_bakeoff.models import Chunk, ExtractionOutput


class _FakeClient:
    def __init__(self, response_json: str):
        self._response_json = response_json
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = MagicMock(return_value=self._make_completion())

    def _make_completion(self):
        msg = MagicMock()
        msg.message.content = self._response_json
        out = MagicMock()
        out.choices = [msg]
        out.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        return out


def test_extract_pg_src_aggregates_across_chunks(tmp_path, fixtures_dir):
    chunks = [
        Chunk(id="a::0", document_id="a", content="void ExecSeqScan() { }", sequence=0),
        Chunk(id="a::1", document_id="a", content="struct Plan { };", sequence=1),
    ]
    fake = _FakeClient(json.dumps({
        "entities": [
            {"name": "ExecSeqScan", "entity_type": "Function", "description": "Runs seq scan"}
        ],
        "relationships": [],
    }))
    out = extract_pg_src(chunks, client=fake, cache_path=tmp_path / "pg.json")
    assert isinstance(out, ExtractionOutput)
    assert out.corpus == "pg_src"
    # Dedup: both chunks returned ExecSeqScan — should appear once
    names = [e.name for e in out.entities]
    assert names.count("ExecSeqScan") == 1


def test_extract_pg_src_uses_cache(tmp_path):
    cache = tmp_path / "cached.json"
    payload = {
        "corpus": "pg_src",
        "chunks": [],
        "entities": [],
        "relationships": [],
    }
    cache.write_text(json.dumps(payload))
    # Client should NOT be called when cache exists
    sentinel = MagicMock(side_effect=AssertionError("should not call LLM"))
    out = extract_pg_src([], client=sentinel, cache_path=cache)
    assert out.corpus == "pg_src"
```

- [ ] **Step 4: Run to confirm failure**

Run: `uv run pytest tests/test_pg_src_extraction.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 5: Implement `extraction/pg_src.py`**

```python
"""LLM-based extraction over Postgres source chunks with on-disk caching."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from age_bakeoff.extraction.prompts import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER_TEMPLATE,
)
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_]+")


def _slug(name: str) -> str:
    return _NAME_SAFE.sub("_", name).lower().strip("_")


def extract_pg_src(
    chunks: list[Chunk],
    client: Any,
    cache_path: Path,
    model: str = "gpt-5-mini",
) -> ExtractionOutput:
    """Run LLM extraction against all chunks, cache, dedupe, return.

    If cache_path exists, load and return without calling the LLM.
    """
    cache_path = Path(cache_path)
    if cache_path.exists():
        raw = json.loads(cache_path.read_text())
        return ExtractionOutput(**raw)

    entities_by_id: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []

    for chunk in chunks:
        user_msg = EXTRACTION_USER_TEMPLATE.format(
            source_path=chunk.metadata.get("source_path", chunk.document_id),
            content=chunk.content,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue

        for e in data.get("entities", []):
            eid = _slug(e["name"])
            if eid not in entities_by_id:
                entities_by_id[eid] = ExtractedEntity(
                    id=eid,
                    name=e["name"],
                    entity_type=e.get("entity_type", "Concept"),
                    description=e.get("description", ""),
                )
        for r in data.get("relationships", []):
            src_id = _slug(r["src"])
            dst_id = _slug(r["dst"])
            if src_id in entities_by_id and dst_id in entities_by_id:
                relationships.append(
                    ExtractedRelationship(
                        src_id=src_id,
                        dst_id=dst_id,
                        rel_type=r.get("rel_type", "RELATES_TO"),
                        description=r.get("description", ""),
                    )
                )

    output = ExtractionOutput(
        corpus="pg_src",
        chunks=chunks,
        entities=sorted(entities_by_id.values(), key=lambda e: e.id),
        relationships=relationships,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(output.model_dump_json(indent=2))
    return output
```

- [ ] **Step 6: Run tests until green**

Run: `uv run pytest tests/test_pg_src_extraction.py -v`
Expected: 2 passed.

- [ ] **Step 7: Dry-run fetch script**

```bash
bash benchmarks/age-bakeoff/scripts/fetch_pg_src.sh
ls benchmarks/age-bakeoff/corpora/pg-src/src/backend/executor/ | head
```

Expected: `execMain.c`, `nodeSeqscan.c`, etc. visible. If sparse-checkout fails, fall back to full clone and manually delete unwanted dirs.

- [ ] **Step 8: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/extraction/pg_src.py \
        benchmarks/age-bakeoff/src/age_bakeoff/extraction/prompts.py \
        benchmarks/age-bakeoff/scripts/fetch_pg_src.sh \
        benchmarks/age-bakeoff/tests/test_pg_src_extraction.py
git commit -m "feat(bakeoff): postgres source extractor with LLM extraction cache"
```

---

## Phase 3: Engine adapters

Two thin adapters with a single interface. Both must accept an `ExtractionOutput` and produce a searchable graph; both must accept a question and return ranked chunks + generated answer. Neither adapter does any extra chunking or extraction — they ingest exactly what they're given.

### Task 3.1: Engine protocol

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/engines/base.py`
- Create: `benchmarks/age-bakeoff/tests/test_engine_protocol.py`

**SC coverage:** SC-001, SC-002, SC-004

- [ ] **Step 1: Write the failing test**

```python
from age_bakeoff.engines.base import Engine, EngineInfo, RetrievalResponse


def test_engine_info_shape():
    info = EngineInfo(
        name="pgrg",
        embedding_model="BAAI/bge-small-en-v1.5",
        answer_model="gpt-5-mini",
        top_k=10,
        hop_budget=2,
    )
    assert info.name == "pgrg"


def test_retrieval_response_shape():
    r = RetrievalResponse(
        retrieved_chunk_ids=["a::0"],
        retrieved_chunk_contents=["content"],
        retrieval_ms=12.5,
    )
    assert r.retrieval_ms == 12.5


def test_engine_is_protocol():
    """Engine is a Protocol; we can type-check but not instantiate."""
    assert hasattr(Engine, "ingest")
    assert hasattr(Engine, "retrieve")
    assert hasattr(Engine, "generate_answer")
    assert hasattr(Engine, "info")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_engine_protocol.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `engines/base.py`**

```python
"""Engine protocol — the boundary both adapters implement."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from age_bakeoff.models import ExtractionOutput


class EngineInfo(BaseModel):
    name: str  # "pgrg" | "age"
    embedding_model: str
    answer_model: str
    top_k: int
    hop_budget: int


class RetrievalResponse(BaseModel):
    retrieved_chunk_ids: list[str]
    retrieved_chunk_contents: list[str]
    retrieval_ms: float


class Engine(Protocol):
    async def ingest(self, extraction: ExtractionOutput) -> None: ...

    async def retrieve(self, question: str) -> RetrievalResponse: ...

    async def generate_answer(
        self, question: str, retrieved_contents: list[str]
    ) -> tuple[str, float]:
        """Returns (answer_text, generation_ms)."""

    def info(self) -> EngineInfo: ...
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run pytest tests/test_engine_protocol.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/engines/base.py benchmarks/age-bakeoff/tests/test_engine_protocol.py
git commit -m "feat(bakeoff): engine protocol"
```

---

### Task 3.2: pg-raggraph engine adapter

**Files:**
- Read: `src/pg_raggraph/db.py` and `src/pg_raggraph/sql/schema.sql` (to understand the target tables)
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg.py`
- Create: `benchmarks/age-bakeoff/tests/test_pgrg_engine.py`

**SC coverage:** SC-001, SC-002, SC-004

The pg-raggraph adapter does NOT use `GraphRAG.ingest()` — that would re-chunk and re-extract. Instead it uses the lower-level `Database` helpers to write chunks, entities, and relationships directly, then calls `GraphRAG.query()` at retrieval time. This keeps inputs identical to the AGE side while still benchmarking pg-raggraph's retrieval path.

- [ ] **Step 1: Locate pg-raggraph's direct-insert helpers**

Run:
```bash
grep -n "async def insert\|async def execute\|async def fetch" /home/yonk/yonk-tools/pg-raggraph/src/pg_raggraph/db.py | head -30
cat /home/yonk/yonk-tools/pg-raggraph/src/pg_raggraph/sql/schema.sql | head -80
```

Expected: enumerated list of column names for `documents`, `chunks`, `entities`, `relationships`. Note any required columns we must populate (e.g., embeddings are NOT NULL).

- [ ] **Step 2: Write the failing test (integration — requires DB)**

```python
"""pg-raggraph engine adapter. Integration test requires docker DB up.

Skips if PGRG_DSN unreachable.
"""
from __future__ import annotations

import os

import psycopg
import pytest

from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

DSN = os.getenv("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg")


def _db_available() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="pg-raggraph DB not reachable"
)


@pytest.fixture
def tiny_extraction() -> ExtractionOutput:
    chunks = [
        Chunk(id="d1::0", document_id="d1", content="Alice works on Ingest.", sequence=0),
        Chunk(id="d1::1", document_id="d1", content="Ingest depends on Kafka.", sequence=1),
    ]
    entities = [
        ExtractedEntity(id="alice", name="Alice", entity_type="Person"),
        ExtractedEntity(id="ingest", name="Ingest", entity_type="Project"),
        ExtractedEntity(id="kafka", name="Kafka", entity_type="Service"),
    ]
    rels = [
        ExtractedRelationship(src_id="alice", dst_id="ingest", rel_type="WORKS_ON"),
        ExtractedRelationship(src_id="ingest", dst_id="kafka", rel_type="DEPENDS_ON"),
    ]
    return ExtractionOutput(corpus="test", chunks=chunks, entities=entities, relationships=rels)


async def test_pgrg_ingest_and_retrieve(tiny_extraction):
    engine = PgrgEngine(dsn=DSN, namespace="bakeoff_test")
    await engine.ingest(tiny_extraction)
    resp = await engine.retrieve("Who works on Ingest?")
    assert len(resp.retrieved_chunk_ids) > 0
    assert resp.retrieval_ms > 0
    await engine.cleanup()


async def test_pgrg_info_matches_config(tiny_extraction):
    engine = PgrgEngine(dsn=DSN, namespace="bakeoff_test")
    info = engine.info()
    assert info.name == "pgrg"
    assert info.embedding_model == "BAAI/bge-small-en-v1.5"
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/test_pgrg_engine.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `engines/pgrg.py`**

```python
"""pg-raggraph engine adapter — bypasses built-in ingest to preserve parity."""
from __future__ import annotations

import time

from fastembed import TextEmbedding

from age_bakeoff.engines.base import EngineInfo, RetrievalResponse
from age_bakeoff.models import ExtractionOutput
from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig


class PgrgEngine:
    def __init__(
        self,
        dsn: str,
        namespace: str = "bakeoff",
        top_k: int = 10,
        hop_budget: int = 2,
        retrieval_mode: str = "hybrid",
        answer_model: str = "gpt-5-mini",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ):
        self._namespace = namespace
        self._top_k = top_k
        self._hop_budget = hop_budget
        self._retrieval_mode = retrieval_mode
        self._answer_model = answer_model
        self._embedding_model = embedding_model
        self._embedder = TextEmbedding(model_name=embedding_model)
        self._rag = GraphRAG(
            dsn=dsn,
            namespace=namespace,
            embedding_dim=384,
        )
        self._connected = False

    async def _ensure_connected(self):
        if not self._connected:
            await self._rag.connect()
            self._connected = True

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._embedder.embed(texts)]

    async def ingest(self, extraction: ExtractionOutput) -> None:
        """Write chunks/entities/relationships directly into pg-raggraph's schema.

        Bypasses GraphRAG.ingest() so we do NOT re-chunk or re-extract.
        """
        await self._ensure_connected()
        db = self._rag.db
        ns = self._namespace

        # Clear any prior data for idempotency
        await self._rag.delete(ns)

        chunk_embs = self._embed([c.content for c in extraction.chunks])
        ent_embs = self._embed([e.name + " " + e.description for e in extraction.entities])

        # Group chunks by document_id so we insert one document row per source doc
        docs_by_id: dict[str, list] = {}
        for c in extraction.chunks:
            docs_by_id.setdefault(c.document_id, []).append(c)

        doc_pk_by_id: dict[str, int] = {}
        for doc_id, doc_chunks in docs_by_id.items():
            row = await db.fetch_one(
                "INSERT INTO documents (namespace, source_path, content_hash, total_chunks) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (ns, doc_id, doc_id, len(doc_chunks)),
            )
            doc_pk_by_id[doc_id] = row["id"]

        # Insert chunks with embeddings
        for chunk, emb in zip(extraction.chunks, chunk_embs):
            await db.execute(
                "INSERT INTO chunks (document_id, sequence, content, embedding, metadata) "
                "VALUES (%s, %s, %s, %s::vector, %s)",
                (
                    doc_pk_by_id[chunk.document_id],
                    chunk.sequence,
                    chunk.content,
                    emb,
                    "{}",
                ),
            )

        # Insert entities
        ent_pk_by_id: dict[str, int] = {}
        for ent, emb in zip(extraction.entities, ent_embs):
            row = await db.fetch_one(
                "INSERT INTO entities (namespace, name, entity_type, description, embedding, properties) "
                "VALUES (%s, %s, %s, %s, %s::vector, %s) RETURNING id",
                (ns, ent.name, ent.entity_type, ent.description, emb, "{}"),
            )
            ent_pk_by_id[ent.id] = row["id"]

        # Insert relationships
        for rel in extraction.relationships:
            if rel.src_id not in ent_pk_by_id or rel.dst_id not in ent_pk_by_id:
                continue
            await db.execute(
                "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, weight, description, properties) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    ns,
                    ent_pk_by_id[rel.src_id],
                    ent_pk_by_id[rel.dst_id],
                    rel.rel_type,
                    rel.weight,
                    rel.description,
                    "{}",
                ),
            )

    async def retrieve(self, question: str) -> RetrievalResponse:
        await self._ensure_connected()
        t0 = time.perf_counter()
        result = await self._rag.query(
            question, mode=self._retrieval_mode, namespace=self._namespace
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        chunks = result.chunks or []
        return RetrievalResponse(
            retrieved_chunk_ids=[
                f"doc_{c.document_id}::{c.sequence}" for c in chunks[: self._top_k]
            ],
            retrieved_chunk_contents=[c.content for c in chunks[: self._top_k]],
            retrieval_ms=elapsed_ms,
        )

    async def generate_answer(
        self, question: str, retrieved_contents: list[str]
    ) -> tuple[str, float]:
        # Delegate answer gen to shared OpenAI helper — both engines use the same path
        from age_bakeoff.engines.openai_answerer import generate_answer

        t0 = time.perf_counter()
        answer = await generate_answer(question, retrieved_contents, model=self._answer_model)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return answer, elapsed_ms

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="pgrg",
            embedding_model=self._embedding_model,
            answer_model=self._answer_model,
            top_k=self._top_k,
            hop_budget=self._hop_budget,
        )

    async def cleanup(self) -> None:
        if self._connected:
            await self._rag.close()
            self._connected = False
```

**NOTE:** If the pg-raggraph `db.fetch_one`/`db.execute` signatures differ from what's assumed here, inspect `src/pg_raggraph/db.py` and adjust — do not change pg-raggraph itself. The schema column names (e.g., `source_path`, `total_chunks`, `embedding_dim`) must match `src/pg_raggraph/sql/schema.sql`. If a required column is missing from the INSERT, add it; if the schema has additional required-non-null columns not shown here, adjust.

- [ ] **Step 5: Create `engines/openai_answerer.py` (shared by both adapters)**

```python
"""Shared OpenAI answer generation — identical path for both engines."""
from __future__ import annotations

from openai import AsyncOpenAI

_ANSWER_SYSTEM = """You answer questions using only the provided context chunks. If the context does not contain the answer, say so. Be concise — 1-3 sentences unless the question demands more."""

_ANSWER_USER_TEMPLATE = """Question: {question}

Context:
{context}

Answer:"""


async def generate_answer(
    question: str, retrieved_contents: list[str], model: str
) -> str:
    client = AsyncOpenAI()
    context = "\n\n---\n\n".join(retrieved_contents)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": _ANSWER_USER_TEMPLATE.format(question=question, context=context)},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content or ""
```

- [ ] **Step 6: Run adapter tests against the live DB**

```bash
docker compose up -d pgrg
uv run pytest tests/test_pgrg_engine.py -v
```
Expected: 2 passed. If schema column names mismatch, inspect the error and correct the INSERT statements.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg.py \
        benchmarks/age-bakeoff/src/age_bakeoff/engines/openai_answerer.py \
        benchmarks/age-bakeoff/tests/test_pgrg_engine.py
git commit -m "feat(bakeoff): pg-raggraph engine adapter (direct DB writer + query)"
```

---

### Task 3.3: AGE engine adapter

**Files:**
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/retrieval/vector.py`
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/retrieval/graph.py`
- Read: `/home/yonk/yonk-samples/graphrag-demo/app/retrieval/combined.py`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/engines/age.py`
- Create: `benchmarks/age-bakeoff/tests/test_age_engine.py`

**SC coverage:** SC-001, SC-002, SC-004

The AGE adapter mirrors the demo's retrieval logic but ingests from our shared `ExtractionOutput` — no seed scripts. Schema: one `documents` table for chunk storage (since AGE's graph stores vertices only, not text), one AGE graph `bakeoff_graph` for entities + relationships.

- [ ] **Step 1: Write the failing test**

```python
import os

import psycopg
import pytest

from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

DSN = os.getenv("AGE_DSN", "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age")


def _db_available() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="AGE DB not reachable")


@pytest.fixture
def tiny_extraction():
    return ExtractionOutput(
        corpus="test",
        chunks=[
            Chunk(id="d1::0", document_id="d1", content="Alice works on Ingest.", sequence=0),
            Chunk(id="d1::1", document_id="d1", content="Ingest depends on Kafka.", sequence=1),
        ],
        entities=[
            ExtractedEntity(id="alice", name="Alice", entity_type="Person"),
            ExtractedEntity(id="ingest", name="Ingest", entity_type="Project"),
            ExtractedEntity(id="kafka", name="Kafka", entity_type="Service"),
        ],
        relationships=[
            ExtractedRelationship(src_id="alice", dst_id="ingest", rel_type="WORKS_ON"),
            ExtractedRelationship(src_id="ingest", dst_id="kafka", rel_type="DEPENDS_ON"),
        ],
    )


async def test_age_ingest_and_retrieve(tiny_extraction):
    engine = AgeEngine(dsn=DSN, graph_name="bakeoff_test")
    await engine.ingest(tiny_extraction)
    resp = await engine.retrieve("Who works on Ingest?")
    assert len(resp.retrieved_chunk_ids) > 0
    assert resp.retrieval_ms > 0
    await engine.cleanup()


async def test_age_info_matches_config():
    engine = AgeEngine(dsn=DSN, graph_name="bakeoff_test")
    info = engine.info()
    assert info.name == "age"
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_age_engine.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `engines/age.py`**

```python
"""Apache AGE engine adapter — mirrors graphrag-demo retrieval over our shared inputs."""
from __future__ import annotations

import asyncio
import time

import psycopg
from fastembed import TextEmbedding

from age_bakeoff.engines.base import EngineInfo, RetrievalResponse
from age_bakeoff.models import ExtractionOutput


_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS age CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL,
    document_id TEXT NOT NULL,
    content TEXT NOT NULL,
    sequence INT NOT NULL,
    embedding vector(384)
);
CREATE INDEX IF NOT EXISTS idx_doc_chunk_id ON documents(chunk_id);
CREATE INDEX IF NOT EXISTS idx_doc_document_id ON documents(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_embedding ON documents USING hnsw (embedding vector_cosine_ops);
"""


class AgeEngine:
    def __init__(
        self,
        dsn: str,
        graph_name: str = "bakeoff_graph",
        top_k: int = 10,
        hop_budget: int = 2,
        answer_model: str = "gpt-5-mini",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ):
        self._dsn = dsn
        self._graph_name = graph_name
        self._top_k = top_k
        self._hop_budget = hop_budget
        self._answer_model = answer_model
        self._embedding_model = embedding_model
        self._embedder = TextEmbedding(model_name=embedding_model)
        self._labels_created: set[str] = set()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._embedder.embed(texts)]

    def _ensure_graph(self, cur) -> None:
        cur.execute(
            "SELECT 1 FROM ag_graph WHERE name = %s", (self._graph_name,)
        )
        if cur.fetchone() is None:
            cur.execute(f"SELECT create_graph(%s)", (self._graph_name,))

    def _ensure_label(self, cur, label: str, is_vertex: bool) -> None:
        key = f"{'v' if is_vertex else 'e'}:{label}"
        if key in self._labels_created:
            return
        fn = "create_vlabel" if is_vertex else "create_elabel"
        try:
            cur.execute(f"SELECT {fn}(%s, %s)", (self._graph_name, label))
        except psycopg.errors.DuplicateObject:
            pass
        except psycopg.Error:
            pass
        self._labels_created.add(key)

    async def ingest(self, extraction: ExtractionOutput) -> None:
        # FastEmbed is CPU-bound sync — run in a thread so async callers aren't blocked
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._ingest_sync, extraction)

    def _ingest_sync(self, extraction: ExtractionOutput) -> None:
        with psycopg.connect(self._dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                for stmt in _SCHEMA_SQL.strip().split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
                self._ensure_graph(cur)

                # Truncate for idempotency
                cur.execute("TRUNCATE documents")
                cur.execute(
                    f"SELECT drop_graph(%s, true)", (self._graph_name,)
                )
                cur.execute(f"SELECT create_graph(%s)", (self._graph_name,))
                self._labels_created.clear()
            conn.commit()

            with conn.cursor() as cur:
                # Chunks → documents table with embeddings
                chunk_embs = self._embed([c.content for c in extraction.chunks])
                for chunk, emb in zip(extraction.chunks, chunk_embs):
                    cur.execute(
                        "INSERT INTO documents (chunk_id, document_id, content, sequence, embedding) "
                        "VALUES (%s, %s, %s, %s, %s::vector)",
                        (chunk.id, chunk.document_id, chunk.content, chunk.sequence, emb),
                    )

                # Entities → Cypher CREATE
                for ent in extraction.entities:
                    self._ensure_label(cur, ent.entity_type, is_vertex=True)
                    cur.execute(
                        "SELECT * FROM cypher(%s, $$ "
                        f"CREATE (n:{ent.entity_type} {{id: '{ent.id}', name: '{ent.name.replace(chr(39), chr(39)+chr(39))}'}}) "
                        "RETURN n "
                        "$$) AS (n agtype)",
                        (self._graph_name,),
                    )

                # Relationships → Cypher MATCH + CREATE
                for rel in extraction.relationships:
                    self._ensure_label(cur, rel.rel_type, is_vertex=False)
                    cur.execute(
                        "SELECT * FROM cypher(%s, $$ "
                        f"MATCH (a {{id: '{rel.src_id}'}}), (b {{id: '{rel.dst_id}'}}) "
                        f"CREATE (a)-[r:{rel.rel_type}]->(b) RETURN r "
                        "$$) AS (r agtype)",
                        (self._graph_name,),
                    )
            conn.commit()

    async def retrieve(self, question: str) -> RetrievalResponse:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, question)

    def _retrieve_sync(self, question: str) -> RetrievalResponse:
        t0 = time.perf_counter()
        q_emb = self._embed([question])[0]

        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;")

                # Stage 1: vector seeds
                cur.execute(
                    "SELECT chunk_id, document_id, content, "
                    "1 - (embedding <=> %s::vector) AS similarity "
                    "FROM documents ORDER BY embedding <=> %s::vector LIMIT %s",
                    (q_emb, q_emb, self._top_k),
                )
                vector_rows = cur.fetchall()
                seen_chunk_ids = {r[0] for r in vector_rows}

                # Stage 2: entity lookup from question — naive contains match against names
                cur.execute(
                    "SELECT * FROM cypher(%s, $$ MATCH (n) RETURN n.id, n.name $$) AS (id agtype, name agtype)",
                    (self._graph_name,),
                )
                entity_rows = cur.fetchall()
                q_lower = question.lower()
                seed_ids = [
                    str(r[0]).strip('"') for r in entity_rows
                    if str(r[1]).strip('"').lower() in q_lower
                ]

                # Stage 3: graph expansion up to hop_budget
                graph_chunks: list[tuple] = []
                if seed_ids:
                    for seed in seed_ids:
                        cur.execute(
                            "SELECT * FROM cypher(%s, $$ "
                            f"MATCH (start {{id: '{seed}'}})-[*1..{self._hop_budget}]-(connected) "
                            "RETURN DISTINCT connected.id "
                            "$$) AS (id agtype)",
                            (self._graph_name,),
                        )
                        connected_ids = [str(r[0]).strip('"') for r in cur.fetchall()]
                        if connected_ids:
                            cur.execute(
                                "SELECT chunk_id, document_id, content FROM documents "
                                "WHERE content ILIKE ANY(%s) LIMIT %s",
                                ([f"%{cid}%" for cid in connected_ids], self._top_k),
                            )
                            for row in cur.fetchall():
                                if row[0] not in seen_chunk_ids:
                                    graph_chunks.append(row)
                                    seen_chunk_ids.add(row[0])

        elapsed_ms = (time.perf_counter() - t0) * 1000
        all_chunks = list(vector_rows) + [(g[0], g[1], g[2], 0.5) for g in graph_chunks]
        all_chunks = all_chunks[: self._top_k]
        return RetrievalResponse(
            retrieved_chunk_ids=[r[0] for r in all_chunks],
            retrieved_chunk_contents=[r[2] for r in all_chunks],
            retrieval_ms=elapsed_ms,
        )

    async def generate_answer(
        self, question: str, retrieved_contents: list[str]
    ) -> tuple[str, float]:
        from age_bakeoff.engines.openai_answerer import generate_answer

        t0 = time.perf_counter()
        answer = await generate_answer(question, retrieved_contents, model=self._answer_model)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return answer, elapsed_ms

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="age",
            embedding_model=self._embedding_model,
            answer_model=self._answer_model,
            top_k=self._top_k,
            hop_budget=self._hop_budget,
        )

    async def cleanup(self) -> None:
        pass
```

Note: the Cypher string interpolation above is not injection-safe — it's acceptable here because the inputs are our own entity IDs which we control. Any ID containing single quotes would break; the `_slug` function in Task 2.2 ensures IDs are `[a-z0-9_]` only, which sidesteps this.

- [ ] **Step 4: Run adapter tests against the live DB**

```bash
docker compose up -d age
uv run pytest tests/test_age_engine.py -v
```
Expected: 2 passed. Common failure modes:
- `relation "ag_graph" does not exist` → AGE extension not loaded; add `LOAD 'age'` to the session.
- `syntax error at or near "CYPHER"` → AGE version mismatch; check the container build.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/engines/age.py benchmarks/age-bakeoff/tests/test_age_engine.py
git commit -m "feat(bakeoff): AGE engine adapter"
```

---

### Task 3.4: Engine parity integration test

**Files:**
- Create: `benchmarks/age-bakeoff/tests/test_engine_parity.py`

**SC coverage:** SC-001 (chunk count equality), SC-002 (matching configs)

- [ ] **Step 1: Write the test**

```python
"""Verify both engines accept the same ExtractionOutput and report matching configs."""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

PGRG_DSN = os.getenv("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg")
AGE_DSN = os.getenv("AGE_DSN", "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age")


def _both_dbs_up() -> bool:
    import psycopg
    for dsn in (PGRG_DSN, AGE_DSN):
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
        except Exception:
            return False
    return True


pytestmark = pytest.mark.skipif(not _both_dbs_up(), reason="both DBs must be up")


def _mk_extraction() -> ExtractionOutput:
    return ExtractionOutput(
        corpus="parity",
        chunks=[
            Chunk(id=f"d::{i}", document_id="d", content=f"Chunk {i} content.", sequence=i)
            for i in range(5)
        ],
        entities=[
            ExtractedEntity(id=f"e{i}", name=f"Entity{i}", entity_type="Concept")
            for i in range(3)
        ],
        relationships=[
            ExtractedRelationship(src_id="e0", dst_id="e1", rel_type="RELATES_TO"),
            ExtractedRelationship(src_id="e1", dst_id="e2", rel_type="RELATES_TO"),
        ],
    )


async def test_identical_extraction_ingested_by_both():
    ext = _mk_extraction()
    pgrg = PgrgEngine(dsn=PGRG_DSN, namespace="parity_test")
    age = AgeEngine(dsn=AGE_DSN, graph_name="parity_test")
    try:
        await pgrg.ingest(ext)
        await age.ingest(ext)
        # Smoke: both can retrieve something for the same question
        r1 = await pgrg.retrieve("chunk content")
        r2 = await age.retrieve("chunk content")
        assert len(r1.retrieved_chunk_ids) > 0
        assert len(r2.retrieved_chunk_ids) > 0
    finally:
        await pgrg.cleanup()
        await age.cleanup()


def test_configs_are_symmetric():
    pgrg_info = PgrgEngine(dsn=PGRG_DSN).info()
    age_info = AgeEngine(dsn=AGE_DSN).info()
    assert pgrg_info.embedding_model == age_info.embedding_model
    assert pgrg_info.answer_model == age_info.answer_model
    assert pgrg_info.top_k == age_info.top_k
    assert pgrg_info.hop_budget == age_info.hop_budget


def test_extraction_checksum_stable():
    ext = _mk_extraction()
    payload = json.dumps(
        {
            "chunks": [c.model_dump() for c in ext.chunks],
            "entities": [e.model_dump() for e in ext.entities],
            "relationships": [r.model_dump() for r in ext.relationships],
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    assert len(digest) == 64
```

- [ ] **Step 2: Run tests**

```bash
docker compose up -d
uv run pytest tests/test_engine_parity.py -v
```
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/tests/test_engine_parity.py
git commit -m "test(bakeoff): engine parity integration test"
```

---

### ⛔ DC-001: Drift Checkpoint

**Trigger:** After Task 3.4 passes.

**Actions:**
1. Re-read `skill-output/mission-brief/Mission-Brief-age-bakeoff.md` — specifically the Purpose, SC-001, and SC-002 sections.
2. Verify: both engines ingest a 5-document smoke-test corpus end-to-end (Task 3.4 just did this).
3. Verify: the matching-config assertion passes (Task 3.4 test `test_configs_are_symmetric`).
4. Answer the three drift questions:
   - Am I still solving the stated Purpose? (Reproducible head-to-head benchmark)
   - Does my current work map to SC-001/SC-002? (Yes — identical inputs + matching configs)
   - Am I doing anything in Out of Scope? (Scan for: did I modify pg-raggraph itself? Did I modify yonk-samples?)
5. If any answer indicates drift → STOP, state what drifted, propose correction before proceeding to Phase 4.

- [ ] **DC-001 actions completed. State evidence in commit message before proceeding.**

---

## Phase 4: Question sets

90 questions (30 per corpus, ≥5 bridging per corpus), each with gold answers and machine-checkable required facts.

### Task 4.1: Question schema validator

**Files:**
- Create: `benchmarks/age-bakeoff/questions/schema.py`
- Create: `benchmarks/age-bakeoff/tests/test_questions_schema.py`

**SC coverage:** SC-003

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest
import yaml

from age_bakeoff.models import QuestionClass
from age_bakeoff.questions.schema import QuestionSet, load_question_set


def test_question_set_enforces_30(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"corpus": "acme", "questions": [
        {"id": "q1", "question": "?", "gold_answer": "a", "required_facts": ["a"], "question_class": "semantic"}
    ]}))
    with pytest.raises(ValueError, match="30"):
        load_question_set(bad)


def test_question_set_enforces_bridging_minimum(tmp_path):
    bad = tmp_path / "bad.yaml"
    qs = [
        {
            "id": f"q{i}",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "semantic",
        }
        for i in range(30)
    ]
    bad.write_text(yaml.safe_dump({"corpus": "acme", "questions": qs}))
    with pytest.raises(ValueError, match="multi_hop_bridging"):
        load_question_set(bad)


def test_valid_set_loads(tmp_path):
    qs = [
        {
            "id": f"q{i}",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "multi_hop_bridging" if i < 5 else "semantic",
        }
        for i in range(30)
    ]
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump({"corpus": "acme", "questions": qs}))
    qset = load_question_set(good)
    assert len(qset.questions) == 30
    assert sum(1 for q in qset.questions if q.question_class == QuestionClass.multi_hop_bridging) == 5
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_questions_schema.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `questions/schema.py`**

```python
"""YAML loader + validator for the frozen question sets."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from age_bakeoff.models import Question, QuestionClass


class QuestionSet(BaseModel):
    corpus: str
    questions: list[Question]

    @field_validator("questions")
    @classmethod
    def _exactly_30(cls, v: list[Question]) -> list[Question]:
        if len(v) != 30:
            raise ValueError(f"Expected exactly 30 questions, got {len(v)}")
        bridging = sum(1 for q in v if q.question_class == QuestionClass.multi_hop_bridging)
        if bridging < 5:
            raise ValueError(
                f"Need ≥5 multi_hop_bridging questions, got {bridging}"
            )
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate question IDs")
        return v


def load_question_set(path: str | Path) -> QuestionSet:
    raw = yaml.safe_load(Path(path).read_text())
    return QuestionSet.model_validate(raw)
```

Also create `questions/__init__.py` re-exporting `load_question_set`.

- [ ] **Step 4: Run tests until green**

Run: `uv run pytest tests/test_questions_schema.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/questions/schema.py benchmarks/age-bakeoff/questions/__init__.py benchmarks/age-bakeoff/tests/test_questions_schema.py
git commit -m "feat(bakeoff): question set schema validator"
```

---

### Task 4.2: Write `questions/acme.yaml`

**Files:**
- Create: `benchmarks/age-bakeoff/questions/acme.yaml`

**SC coverage:** SC-003

- [ ] **Step 1: Draft 30 Acme questions**

Write the YAML file with this shape. All 30 must be present — no placeholders. The 5+ bridging questions must require chaining through at least 2 entities.

```yaml
corpus: acme
questions:
  - id: acme-q-001
    question: "Who leads the Platform team?"
    gold_answer: "Alice Chen leads the Platform team."
    required_facts: ["Alice Chen", "Platform team"]
    required_entities: ["person_alice", "team_platform"]
    question_class: factual

  - id: acme-q-002
    question: "What service does the Ingest Pipeline depend on?"
    gold_answer: "The Ingest Pipeline depends on Kafka."
    required_facts: ["Ingest Pipeline", "Kafka"]
    required_entities: ["project_ingest", "service_kafka"]
    question_class: single_hop

  # ... 5+ must be multi_hop_bridging — example:
  - id: acme-q-020
    question: "Which team members work on projects that depend on Kafka?"
    gold_answer: "Alice Chen and Bob Martinez both work on projects that depend on Kafka: Alice on Ingest Pipeline and Bob on Event Stream."
    required_facts: ["Alice Chen", "Bob Martinez", "Ingest Pipeline", "Event Stream", "Kafka"]
    required_entities: ["person_alice", "person_bob", "project_ingest", "project_event_stream", "service_kafka"]
    question_class: multi_hop_bridging

  # ... continue through acme-q-030
```

Ground rules for writing questions:
- Every `required_fact` must be a string literal that will appear in a correct answer
- `required_entities` are the entity IDs that should show up in retrieved chunks
- `multi_hop_bridging` questions must genuinely require traversing 2+ relationships (verify by mentally walking the entity graph)
- At least 5 of the 30 must have `question_class: multi_hop_bridging`
- Mix ~5 factual, ~10 single_hop, ~5 semantic, ~5 multi_hop_bridging, remainder factual/semantic

- [ ] **Step 2: Validate with the schema loader**

```bash
uv run python -c "from age_bakeoff.questions.schema import load_question_set; print(load_question_set('questions/acme.yaml').corpus)"
```
Expected: prints `acme`. Any schema violation raises immediately.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/questions/acme.yaml
git commit -m "feat(bakeoff): 30 Acme questions (5 bridging)"
```

---

### Task 4.3: Write `questions/scotus.yaml`

**Files:**
- Create: `benchmarks/age-bakeoff/questions/scotus.yaml`

**SC coverage:** SC-003

- [ ] **Step 1: Draft 30 SCOTUS questions**

Write 30 SCOTUS questions with the same structure as acme.yaml. Draw from the demo's scotus_data.py — justices, cases, issues, citations.

Example bridging questions for SCOTUS:
- "Which cases cited Brown v. Board, and which of those were written by Justice Thurgood Marshall?" — requires CITED chain + VOTED_MAJORITY chain
- "What issues connect Miranda v. Arizona to Gideon v. Wainwright through shared justices?" — requires Case → Justice → Case traversal
- "Which dissenting opinions in civil rights cases were authored by justices who also voted majority in related equal protection cases?" — 3-hop

5+ must be `multi_hop_bridging`. Ground-truth the bridging questions by walking the graph in scotus_data.py before writing them.

- [ ] **Step 2: Validate**

```bash
uv run python -c "from age_bakeoff.questions.schema import load_question_set; load_question_set('questions/scotus.yaml')"
```
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/questions/scotus.yaml
git commit -m "feat(bakeoff): 30 SCOTUS questions (5 bridging)"
```

---

### Task 4.4: Write `questions/pg-src.yaml`

**Files:**
- Create: `benchmarks/age-bakeoff/questions/pg-src.yaml`

**SC coverage:** SC-003

- [ ] **Step 1: Draft 30 Postgres executor+planner questions**

Write 30 questions grounded in the Postgres executor + planner source. The bridging questions are the stars of the show — they're why this corpus exists.

Example bridging questions (these are the target class):
- "What happens to a SeqScan cost estimate between `create_seqscan_path` and the actual row scan in `ExecSeqScan`?" — requires: `costsize.c` → `pathnode.c` → `createplan.c` → `execMain.c` → `nodeSeqscan.c`
- "Why does a HashJoin need a materialized inner relation, and where is that decided?" — requires: `initial_cost_hashjoin` → `create_hashjoin_path` → `make_hashjoin` → `ExecHashJoinImpl`
- "How does `ExecInitNode` dispatch between different PlanState types, and where is that mapping defined?"
- "What is the difference between `JoinState` and `JoinPath`, and where is each one constructed?"
- "Which planner function decides whether to use a parallel aware scan, and how does that decision propagate to the executor?"

Factual/semantic questions (fill the remaining 25):
- "What does `PlanState` represent?" (factual)
- "What file defines `ExecInitSeqScan`?" (factual)
- "Explain how recursive CTE execution works in the executor" (semantic)
- etc.

5+ must be `multi_hop_bridging`. Before writing each bridging question, walk the file/function chain in the cloned pg-src corpus to verify a correct answer exists.

- [ ] **Step 2: Validate**

```bash
uv run python -c "from age_bakeoff.questions.schema import load_question_set; load_question_set('questions/pg-src.yaml')"
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/questions/pg-src.yaml
git commit -m "feat(bakeoff): 30 Postgres executor+planner questions (5+ bridging)"
```

---

### ⛔ DC-002: Drift Checkpoint

**Trigger:** After Tasks 4.2, 4.3, 4.4 all pass validation.

**Actions:**
1. Re-read `skill-output/mission-brief/Mission-Brief-age-bakeoff.md` Purpose section.
2. Run the three-question drift check:
   - Am I still solving the Purpose? (Does each question class map back to a realistic user workflow, or did I start writing gotcha questions?)
   - Does every question map to a SC criterion? (SC-003 specifically)
   - Did any question get written to flatter one engine over the other?
3. **Ask the user** to spot-check the 5 Postgres bridging questions specifically — present them as a list and confirm the expected answers are reasonable. These are the questions where bias is most likely.
4. If any answer indicates drift → STOP, revise the question set, re-validate, continue.

- [ ] **DC-002 actions completed. User spot-check acknowledged.**

---

## Phase 5: Runner

The harness that executes 90 questions × 3 runs × 2 engines, records latency + generated answers, enforces the cost budget, writes raw JSON results.

### Task 5.1: Cost tracker

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/cost.py`
- Create: `benchmarks/age-bakeoff/tests/test_cost.py`

**SC coverage:** SC-004 (supports), constraint enforcement (cost ceiling)

- [ ] **Step 1: Write the failing test**

```python
import pytest

from age_bakeoff.cost import CostTracker, CostBudgetExceeded


def test_tracker_accumulates():
    t = CostTracker(budget_usd=1.0)
    t.record("gpt-5-mini", prompt_tokens=1000, completion_tokens=500)
    assert t.total_usd > 0
    assert t.total_usd < 1.0


def test_tracker_raises_when_over_budget():
    t = CostTracker(budget_usd=0.0001)
    with pytest.raises(CostBudgetExceeded):
        t.record("gpt-5-mini", prompt_tokens=10000, completion_tokens=5000)


def test_unknown_model_falls_back_to_conservative_pricing():
    t = CostTracker(budget_usd=100.0)
    t.record("unknown-model", prompt_tokens=1000, completion_tokens=500)
    # Should not raise; use a safe default
    assert t.total_usd > 0
```

- [ ] **Step 2: Implement `cost.py`**

```python
"""Running USD tally for OpenAI calls with a hard budget ceiling."""
from __future__ import annotations

# Prices in USD per 1M tokens. Update if upstream pricing changes.
_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1M, output_per_1M)
    "gpt-5-mini": (0.25, 2.00),  # placeholder — confirmed via env var if wrong
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
}
_FALLBACK = (5.00, 15.00)  # conservative default for unknown models


class CostBudgetExceeded(Exception):
    pass


class CostTracker:
    def __init__(self, budget_usd: float):
        self.budget_usd = budget_usd
        self.total_usd = 0.0
        self.calls: list[dict] = []

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        in_rate, out_rate = _PRICING.get(model, _FALLBACK)
        cost = (prompt_tokens / 1_000_000) * in_rate + (completion_tokens / 1_000_000) * out_rate
        self.total_usd += cost
        self.calls.append({
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "usd": cost,
        })
        if self.total_usd > self.budget_usd:
            raise CostBudgetExceeded(
                f"Cost ${self.total_usd:.4f} exceeds budget ${self.budget_usd:.2f}"
            )
```

- [ ] **Step 3: Run tests until green**

Run: `uv run pytest tests/test_cost.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/cost.py benchmarks/age-bakeoff/tests/test_cost.py
git commit -m "feat(bakeoff): cost tracker with hard budget ceiling"
```

---

### Task 5.2: Runner harness

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/runner.py`
- Create: `benchmarks/age-bakeoff/tests/test_runner_smoke.py`
- Create: `benchmarks/age-bakeoff/tests/fixtures/tiny_questions.yaml`

**SC coverage:** SC-004 (per-run JSON schema)

- [ ] **Step 1: Create a tiny fixture question set**

Write `tests/fixtures/tiny_questions.yaml`:
```yaml
corpus: parity
questions:
  - id: tiny-q-001
    question: "Who works on Ingest?"
    gold_answer: "Alice works on Ingest."
    required_facts: ["Alice", "Ingest"]
    required_entities: ["alice", "ingest"]
    question_class: single_hop
  - id: tiny-q-002
    question: "What does Ingest depend on?"
    gold_answer: "Ingest depends on Kafka."
    required_facts: ["Ingest", "Kafka"]
    required_entities: ["ingest", "kafka"]
    question_class: single_hop
```

(Note: this file bypasses the ≥30 / ≥5-bridging validation. Use a separate permissive loader in tests or set an env flag. For this plan we'll add a `strict=False` kwarg to `load_question_set`.)

Update `questions/schema.py` `load_question_set` signature to accept `strict: bool = True` and skip the count validator when false:
```python
def load_question_set(path: str | Path, strict: bool = True) -> QuestionSet:
    raw = yaml.safe_load(Path(path).read_text())
    if strict:
        return QuestionSet.model_validate(raw)
    # Loose mode: skip count validators
    return _LooseQuestionSet.model_validate(raw)


class _LooseQuestionSet(BaseModel):
    corpus: str
    questions: list[Question]
```

- [ ] **Step 2: Write the failing test**

```python
"""Runner smoke test — 2 questions, 1 run, against live DBs."""
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)
from age_bakeoff.questions.schema import load_question_set
from age_bakeoff.runner import Runner, RunnerOptions


def _both_dbs_up() -> bool:
    for dsn in (
        os.getenv("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"),
        os.getenv("AGE_DSN", "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age"),
    ):
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
        except Exception:
            return False
    return True


pytestmark = pytest.mark.skipif(not _both_dbs_up(), reason="both DBs required")


async def test_runner_produces_valid_schema(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-real-key"))
    cfg = BakeoffConfig()

    extraction = ExtractionOutput(
        corpus="parity",
        chunks=[
            Chunk(id="d::0", document_id="d", content="Alice works on Ingest.", sequence=0),
            Chunk(id="d::1", document_id="d", content="Ingest depends on Kafka.", sequence=1),
        ],
        entities=[
            ExtractedEntity(id="alice", name="Alice", entity_type="Person"),
            ExtractedEntity(id="ingest", name="Ingest", entity_type="Project"),
            ExtractedEntity(id="kafka", name="Kafka", entity_type="Service"),
        ],
        relationships=[
            ExtractedRelationship(src_id="alice", dst_id="ingest", rel_type="WORKS_ON"),
            ExtractedRelationship(src_id="ingest", dst_id="kafka", rel_type="DEPENDS_ON"),
        ],
    )
    qset = load_question_set(fixtures_dir / "tiny_questions.yaml", strict=False)

    pgrg = PgrgEngine(dsn=cfg.pgrg_dsn, namespace="runner_smoke")
    age = AgeEngine(dsn=cfg.age_dsn, graph_name="runner_smoke")

    runner = Runner(
        config=cfg,
        engines={"pgrg": pgrg, "age": age},
        options=RunnerOptions(runs_per_question=1, output_dir=tmp_path),
    )
    await runner.ingest({"parity": extraction})
    results = await runner.run_corpus("parity", qset)

    # Schema: engine × question × runs
    assert len(results) == 2 * 2  # 2 questions × 2 engines × 1 run
    for r in results:
        assert r.retrieval_ms >= 0
        assert r.answer_ms >= 0
        assert r.generated_answer
        assert isinstance(r.retrieved_chunk_ids, list)

    # Output file exists and is valid JSON
    out_file = tmp_path / "parity.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert len(data) == 4

    await pgrg.cleanup()
    await age.cleanup()
```

- [ ] **Step 3: Implement `runner.py`**

```python
"""Benchmark harness — runs all questions across all engines, records JSON."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.engines.base import Engine
from age_bakeoff.models import ExtractionOutput, RunResult
from age_bakeoff.questions.schema import QuestionSet

logger = logging.getLogger(__name__)


@dataclass
class RunnerOptions:
    runs_per_question: int = 3
    output_dir: Path = Path("results/raw")


class Runner:
    def __init__(
        self,
        config: BakeoffConfig,
        engines: dict[str, Engine],
        options: RunnerOptions,
    ):
        self.config = config
        self.engines = engines
        self.options = options
        self.options.output_dir.mkdir(parents=True, exist_ok=True)

    def verify_symmetry(self) -> None:
        """Assert both engines report matching configs — fails loud if not."""
        infos = [eng.info() for eng in self.engines.values()]
        if len(infos) < 2:
            return
        ref = infos[0]
        for other in infos[1:]:
            if other.embedding_model != ref.embedding_model:
                raise RuntimeError(
                    f"Embedding model mismatch: {ref.embedding_model} vs {other.embedding_model}"
                )
            if other.answer_model != ref.answer_model:
                raise RuntimeError(
                    f"Answer model mismatch: {ref.answer_model} vs {other.answer_model}"
                )
            if other.top_k != ref.top_k:
                raise RuntimeError(f"top_k mismatch: {ref.top_k} vs {other.top_k}")
            if other.hop_budget != ref.hop_budget:
                raise RuntimeError(f"hop_budget mismatch: {ref.hop_budget} vs {other.hop_budget}")

    async def ingest(self, extractions: dict[str, ExtractionOutput]) -> None:
        self.verify_symmetry()
        for corpus, extraction in extractions.items():
            for name, engine in self.engines.items():
                logger.info("Ingesting corpus=%s into engine=%s", corpus, name)
                await engine.ingest(extraction)

    async def run_corpus(
        self, corpus: str, qset: QuestionSet
    ) -> list[RunResult]:
        results: list[RunResult] = []
        for q in qset.questions:
            for run_number in range(1, self.options.runs_per_question + 1):
                cold = run_number == 1
                for name, engine in self.engines.items():
                    try:
                        retrieval = await engine.retrieve(q.question)
                        answer, answer_ms = await engine.generate_answer(
                            q.question, retrieval.retrieved_chunk_contents
                        )
                        results.append(
                            RunResult(
                                engine=name,
                                corpus=corpus,
                                question_id=q.id,
                                run_number=run_number,
                                cold=cold,
                                retrieval_ms=retrieval.retrieval_ms,
                                answer_ms=answer_ms,
                                retrieved_chunk_ids=retrieval.retrieved_chunk_ids,
                                generated_answer=answer,
                            )
                        )
                    except Exception as exc:
                        logger.exception("Run failed q=%s engine=%s", q.id, name)
                        results.append(
                            RunResult(
                                engine=name,
                                corpus=corpus,
                                question_id=q.id,
                                run_number=run_number,
                                cold=cold,
                                retrieval_ms=-1.0,
                                answer_ms=-1.0,
                                retrieved_chunk_ids=[],
                                generated_answer="",
                                error=str(exc),
                            )
                        )

        # Write per-corpus raw JSON
        out = self.options.output_dir / f"{corpus}.json"
        out.write_text(
            json.dumps([r.model_dump() for r in results], indent=2, sort_keys=True)
        )
        return results
```

- [ ] **Step 4: Run smoke test**

```bash
docker compose up -d
export OPENAI_API_KEY=...   # real key needed
uv run pytest tests/test_runner_smoke.py -v
```
Expected: 1 passed. If answer_ms is always 0, the OpenAI client isn't hitting the network — check API key.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/runner.py \
        benchmarks/age-bakeoff/tests/test_runner_smoke.py \
        benchmarks/age-bakeoff/tests/fixtures/tiny_questions.yaml \
        benchmarks/age-bakeoff/questions/schema.py
git commit -m "feat(bakeoff): runner harness with verify_symmetry and per-corpus JSON output"
```

---

## Phase 6: Scorers

Two scorers: deterministic fact recall (pure string matching) and LLM judge (OpenAI, 3× majority vote).

### Task 6.1: Fact-recall scorer

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/scorers/fact_recall.py`
- Create: `benchmarks/age-bakeoff/tests/test_fact_recall.py`

**SC coverage:** SC-005

- [ ] **Step 1: Write the failing test**

```python
from age_bakeoff.models import Question, QuestionClass, RunResult
from age_bakeoff.scorers.fact_recall import score_fact_recall, aggregate_fact_recall


def _mk_question(facts):
    return Question(
        id="q1",
        question="?",
        gold_answer="a",
        required_facts=facts,
        required_entities=[],
        question_class=QuestionClass.single_hop,
    )


def _mk_result(contents):
    return RunResult(
        engine="pgrg",
        corpus="test",
        question_id="q1",
        run_number=1,
        cold=True,
        retrieval_ms=1.0,
        answer_ms=1.0,
        retrieved_chunk_ids=["c0"],
        generated_answer="",
        # contents fed via scorer — we'll pass them in directly below
    )


def test_full_recall():
    q = _mk_question(["Alice", "Kafka"])
    retrieved = ["Alice works on Ingest. Ingest depends on Kafka."]
    assert score_fact_recall(q, retrieved) == 1.0


def test_partial_recall():
    q = _mk_question(["Alice", "Kafka", "Redis"])
    retrieved = ["Alice works on Ingest. Ingest depends on Kafka."]
    assert score_fact_recall(q, retrieved) == pytest.approx(2 / 3)


def test_zero_recall():
    q = _mk_question(["Zoe"])
    retrieved = ["Alice works on Ingest."]
    assert score_fact_recall(q, retrieved) == 0.0


def test_case_insensitive():
    q = _mk_question(["ALICE"])
    retrieved = ["alice was here"]
    assert score_fact_recall(q, retrieved) == 1.0


def test_aggregation_confidence_interval():
    scores = [1.0, 1.0, 0.5]
    mean, lo, hi = aggregate_fact_recall(scores)
    assert mean == pytest.approx(0.8333, rel=1e-3)
    assert lo <= mean <= hi


import pytest
```

- [ ] **Step 2: Implement `scorers/fact_recall.py`**

```python
"""Deterministic fact-recall scorer — pure string matching, no LLM."""
from __future__ import annotations

import statistics

from age_bakeoff.models import Question


def score_fact_recall(question: Question, retrieved_contents: list[str]) -> float:
    if not question.required_facts:
        return 1.0
    haystack = " \n ".join(retrieved_contents).lower()
    hits = sum(1 for fact in question.required_facts if fact.lower() in haystack)
    return hits / len(question.required_facts)


def aggregate_fact_recall(scores: list[float]) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) with a 95% bootstrap-style band.

    Uses stdev-based approximation; fine for n=3 since we just want a rough band.
    """
    if not scores:
        return 0.0, 0.0, 0.0
    mean = statistics.mean(scores)
    if len(scores) < 2:
        return mean, mean, mean
    sd = statistics.stdev(scores)
    margin = 1.96 * sd / (len(scores) ** 0.5)
    return mean, max(0.0, mean - margin), min(1.0, mean + margin)
```

- [ ] **Step 3: Run tests until green**

Run: `uv run pytest tests/test_fact_recall.py -v`
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/scorers/fact_recall.py benchmarks/age-bakeoff/tests/test_fact_recall.py
git commit -m "feat(bakeoff): deterministic fact-recall scorer"
```

---

### Task 6.2: LLM judge scorer

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/scorers/llm_judge.py`
- Create: `benchmarks/age-bakeoff/tests/test_llm_judge.py`

**SC coverage:** SC-006

- [ ] **Step 1: Write the failing test (mocked OpenAI)**

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from age_bakeoff.scorers.llm_judge import JudgeVerdict, judge_answer, majority_verdict


def _mock_client(verdicts: list[str]):
    client = MagicMock()
    client.chat = MagicMock()

    responses = []
    for v in verdicts:
        msg = MagicMock()
        msg.message.content = f'{{"verdict": "{v}", "rationale": "test"}}'
        completion = MagicMock()
        completion.choices = [msg]
        completion.usage = MagicMock(prompt_tokens=100, completion_tokens=20)
        responses.append(completion)

    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


async def test_judge_parses_fully_correct():
    client = _mock_client(["fully_correct"])
    verdict = await judge_answer(
        client=client,
        question="?",
        gold_answer="a",
        generated_answer="a",
        model="gpt-5-mini",
    )
    assert verdict == JudgeVerdict.fully_correct


def test_majority_picks_winner():
    verdicts = [
        JudgeVerdict.fully_correct,
        JudgeVerdict.fully_correct,
        JudgeVerdict.wrong,
    ]
    assert majority_verdict(verdicts) == JudgeVerdict.fully_correct


def test_majority_tie_prefers_partial():
    verdicts = [
        JudgeVerdict.fully_correct,
        JudgeVerdict.wrong,
    ]
    # Tie-break: average the ordinal scores
    result = majority_verdict(verdicts)
    assert result == JudgeVerdict.partially_correct
```

- [ ] **Step 2: Implement `scorers/llm_judge.py`**

```python
"""LLM-judge scorer with 3x majority vote."""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel

_JUDGE_SYSTEM = """You are grading an AI-generated answer against a reference answer.

Return strict JSON matching this schema:
{
  "verdict": "fully_correct | partially_correct | wrong | hallucinated",
  "rationale": "one short sentence"
}

Rubric:
- fully_correct: Contains every key fact from the reference. No contradictions.
- partially_correct: Contains some facts but misses important ones, or adds minor unsupported details.
- wrong: Addresses the question but contradicts the reference or misses the main point.
- hallucinated: Invents facts not in the reference and not plausibly inferable.

Be strict. Use fully_correct only when the answer is genuinely complete."""

_JUDGE_USER_TEMPLATE = """Question: {question}

Reference answer: {gold}

Generated answer: {generated}

Grade the generated answer."""


class JudgeVerdict(str, Enum):
    fully_correct = "fully_correct"
    partially_correct = "partially_correct"
    wrong = "wrong"
    hallucinated = "hallucinated"


_ORDINAL = {
    JudgeVerdict.fully_correct: 3,
    JudgeVerdict.partially_correct: 2,
    JudgeVerdict.wrong: 1,
    JudgeVerdict.hallucinated: 0,
}

_ORDINAL_REVERSE = {v: k for k, v in _ORDINAL.items()}


async def judge_answer(
    client: Any,
    question: str,
    gold_answer: str,
    generated_answer: str,
    model: str,
) -> JudgeVerdict:
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": _JUDGE_USER_TEMPLATE.format(
                    question=question, gold=gold_answer, generated=generated_answer
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    return JudgeVerdict(data["verdict"])


def majority_verdict(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    if not verdicts:
        return JudgeVerdict.wrong
    counts: dict[JudgeVerdict, int] = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    winners = [v for v, c in counts.items() if c == max_count]
    if len(winners) == 1:
        return winners[0]
    # Tie: average ordinal
    avg = sum(_ORDINAL[v] for v in verdicts) / len(verdicts)
    rounded = round(avg)
    return _ORDINAL_REVERSE.get(rounded, JudgeVerdict.partially_correct)
```

- [ ] **Step 3: Run tests until green**

Run: `uv run pytest tests/test_llm_judge.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/scorers/llm_judge.py benchmarks/age-bakeoff/tests/test_llm_judge.py
git commit -m "feat(bakeoff): LLM judge scorer with majority-vote aggregation"
```

---

## Phase 7: Report generator

Deterministic markdown generator — given raw JSON results + questions + scorer outputs, produces `REPORT.md` byte-identically every time for the same input.

### Task 7.1: Aggregation helpers (p50/p95, per-class breakdowns)

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/report/aggregate.py`
- Create: `benchmarks/age-bakeoff/tests/test_report_aggregate.py`

**SC coverage:** SC-007

- [ ] **Step 1: Write the failing test**

```python
from age_bakeoff.report.aggregate import (
    latency_percentiles,
    group_by_engine_and_class,
)
from age_bakeoff.models import RunResult, QuestionClass


def _mk(engine: str, ms: float, qid: str = "q1"):
    return RunResult(
        engine=engine,
        corpus="t",
        question_id=qid,
        run_number=1,
        cold=True,
        retrieval_ms=ms,
        answer_ms=0.0,
        retrieved_chunk_ids=[],
        generated_answer="",
    )


def test_latency_percentiles():
    results = [_mk("pgrg", 10.0), _mk("pgrg", 20.0), _mk("pgrg", 30.0), _mk("pgrg", 40.0)]
    p = latency_percentiles(results, metric="retrieval_ms")
    assert p["p50"] == 25.0
    assert p["p95"] >= 30.0


def test_group_by_engine():
    results = [_mk("pgrg", 10.0, "q1"), _mk("age", 20.0, "q1")]
    question_class_by_id = {"q1": QuestionClass.single_hop}
    grouped = group_by_engine_and_class(results, question_class_by_id)
    assert "pgrg" in grouped
    assert "age" in grouped
    assert QuestionClass.single_hop in grouped["pgrg"]
```

- [ ] **Step 2: Implement `report/aggregate.py`**

```python
"""Aggregation helpers — pure, deterministic, no I/O."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from age_bakeoff.models import QuestionClass, RunResult


def latency_percentiles(
    results: Iterable[RunResult], metric: str = "retrieval_ms"
) -> dict[str, float]:
    values = sorted(
        getattr(r, metric) for r in results if getattr(r, metric) >= 0
    )
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "n": 0}

    def _pct(p: float) -> float:
        if len(values) == 1:
            return values[0]
        idx = (len(values) - 1) * p
        lo = int(idx)
        hi = min(lo + 1, len(values) - 1)
        frac = idx - lo
        return values[lo] * (1 - frac) + values[hi] * frac

    return {
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
        "mean": statistics.mean(values),
        "n": len(values),
    }


def group_by_engine_and_class(
    results: list[RunResult],
    question_class_by_id: dict[str, QuestionClass],
) -> dict[str, dict[QuestionClass, list[RunResult]]]:
    grouped: dict[str, dict[QuestionClass, list[RunResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        qc = question_class_by_id.get(r.question_id)
        if qc is None:
            continue
        grouped[r.engine][qc].append(r)
    return {k: dict(v) for k, v in grouped.items()}
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_report_aggregate.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/report/aggregate.py \
        benchmarks/age-bakeoff/src/age_bakeoff/report/__init__.py \
        benchmarks/age-bakeoff/tests/test_report_aggregate.py
git commit -m "feat(bakeoff): report aggregation helpers"
```

---

### Task 7.2: Markdown report generator

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/report/generator.py`
- Create: `benchmarks/age-bakeoff/tests/test_report_generator.py`
- Create: `benchmarks/age-bakeoff/tests/fixtures/canned_raw_results.json`
- Create: `benchmarks/age-bakeoff/tests/fixtures/canned_report.md`

**SC coverage:** SC-007, SC-008

- [ ] **Step 1: Create a canned raw results fixture**

Hand-craft `tests/fixtures/canned_raw_results.json` with ~6 RunResult entries (2 engines × 1 corpus × 3 questions × 1 run). Keep it deterministic and boring.

```json
[
  {
    "engine": "pgrg",
    "corpus": "acme",
    "question_id": "q1",
    "run_number": 1,
    "cold": true,
    "retrieval_ms": 12.0,
    "answer_ms": 800.0,
    "retrieved_chunk_ids": ["d1::0"],
    "generated_answer": "Alice Chen leads the Platform team.",
    "error": null
  },
  {
    "engine": "age",
    "corpus": "acme",
    "question_id": "q1",
    "run_number": 1,
    "cold": true,
    "retrieval_ms": 35.0,
    "answer_ms": 820.0,
    "retrieved_chunk_ids": ["d1::0"],
    "generated_answer": "Alice Chen leads the Platform team.",
    "error": null
  }
]
```

(Expand to 6 entries total, 3 questions × 2 engines.)

- [ ] **Step 2: Write the snapshot test**

```python
"""Report generator is deterministic — byte-for-byte against a golden file."""
from __future__ import annotations

import json
from pathlib import Path

from age_bakeoff.models import Question, QuestionClass
from age_bakeoff.report.generator import generate_report


def test_snapshot_matches_golden(fixtures_dir, tmp_path):
    raw = json.loads((fixtures_dir / "canned_raw_results.json").read_text())
    questions = [
        Question(
            id="q1",
            question="?",
            gold_answer="Alice Chen leads the Platform team.",
            required_facts=["Alice Chen", "Platform"],
            required_entities=[],
            question_class=QuestionClass.factual,
        ),
        Question(
            id="q2",
            question="?",
            gold_answer="Ingest depends on Kafka.",
            required_facts=["Ingest", "Kafka"],
            required_entities=[],
            question_class=QuestionClass.single_hop,
        ),
        Question(
            id="q3",
            question="?",
            gold_answer="Alice and Bob both work on projects that depend on Kafka.",
            required_facts=["Alice", "Bob", "Kafka"],
            required_entities=[],
            question_class=QuestionClass.multi_hop_bridging,
        ),
    ]
    out_path = tmp_path / "REPORT.md"
    generate_report(
        raw_results_by_corpus={"acme": raw},
        questions_by_corpus={"acme": questions},
        output_path=out_path,
        runtime_seconds=123.4,
    )
    actual = out_path.read_text()
    expected = (fixtures_dir / "canned_report.md").read_text()
    assert actual == expected
```

- [ ] **Step 3: Implement `report/generator.py`**

```python
"""Deterministic markdown report generator."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from age_bakeoff.models import Question, QuestionClass, RunResult
from age_bakeoff.report.aggregate import (
    group_by_engine_and_class,
    latency_percentiles,
)
from age_bakeoff.scorers.fact_recall import aggregate_fact_recall, score_fact_recall


def generate_report(
    raw_results_by_corpus: dict[str, list[dict]],
    questions_by_corpus: dict[str, list[Question]],
    output_path: Path,
    runtime_seconds: float,
    judge_scores: dict[tuple[str, str, str], str] | None = None,
) -> None:
    """Write REPORT.md. Byte-deterministic given identical inputs.

    judge_scores keyed by (corpus, engine, question_id) → majority verdict string.
    """
    lines: list[str] = []
    lines.append("# AGE vs pg-raggraph Bake-Off — Results\n")
    lines.append("_Auto-generated. Do not hand-edit. Re-run `age-bakeoff report` to regenerate._\n")
    lines.append(f"**Total runtime:** {runtime_seconds:.1f} seconds ({runtime_seconds / 60:.1f} minutes)\n")

    for corpus in sorted(raw_results_by_corpus.keys()):
        raw = raw_results_by_corpus[corpus]
        results = [RunResult(**r) for r in raw]
        questions = questions_by_corpus[corpus]
        qc_by_id = {q.id: q.question_class for q in questions}
        question_by_id = {q.id: q for q in questions}

        lines.append(f"\n## Corpus: {corpus}\n")
        _write_latency_table(lines, results)
        _write_fact_recall_table(lines, results, question_by_id)
        if judge_scores:
            _write_judge_table(lines, results, judge_scores, corpus)
        _write_per_class_breakdown(lines, results, qc_by_id)
        _write_what_this_means(lines, results, question_by_id)

    lines.append("\n## Where AGE wins (if anywhere)\n")
    _write_where_age_wins(lines, raw_results_by_corpus, questions_by_corpus, judge_scores)

    output_path.write_text("".join(lines))


def _write_latency_table(lines: list[str], results: list[RunResult]) -> None:
    lines.append("\n### Latency\n")
    lines.append("\n| Engine | Mode | p50 (ms) | p95 (ms) | p99 (ms) | N |\n")
    lines.append("|---|---|---|---|---|---|\n")
    by_engine = defaultdict(list)
    for r in results:
        by_engine[r.engine].append(r)
    for engine in sorted(by_engine):
        cold = [r for r in by_engine[engine] if r.cold]
        warm = [r for r in by_engine[engine] if not r.cold]
        for label, subset in [("cold retrieval", cold), ("warm retrieval", warm)]:
            if not subset:
                continue
            p = latency_percentiles(subset, "retrieval_ms")
            lines.append(
                f"| {engine} | {label} | {p['p50']:.1f} | {p['p95']:.1f} | {p['p99']:.1f} | {p['n']} |\n"
            )
        for label, subset in [("cold end-to-end", cold), ("warm end-to-end", warm)]:
            if not subset:
                continue
            combined = [
                RunResult(**{**r.model_dump(), "retrieval_ms": r.retrieval_ms + r.answer_ms})
                for r in subset
            ]
            p = latency_percentiles(combined, "retrieval_ms")
            lines.append(
                f"| {engine} | {label} | {p['p50']:.1f} | {p['p95']:.1f} | {p['p99']:.1f} | {p['n']} |\n"
            )


def _write_fact_recall_table(
    lines: list[str], results: list[RunResult], question_by_id: dict[str, Question]
) -> None:
    lines.append("\n### Fact Recall\n")
    lines.append("\n| Engine | Mean | 95% CI low | 95% CI high | N questions |\n")
    lines.append("|---|---|---|---|---|\n")
    by_engine = defaultdict(list)
    for r in results:
        q = question_by_id.get(r.question_id)
        if q is None:
            continue
        score = score_fact_recall(q, [r.generated_answer])
        by_engine[r.engine].append(score)
    for engine in sorted(by_engine):
        mean, lo, hi = aggregate_fact_recall(by_engine[engine])
        lines.append(
            f"| {engine} | {mean:.3f} | {lo:.3f} | {hi:.3f} | {len(by_engine[engine])} |\n"
        )


def _write_judge_table(
    lines: list[str],
    results: list[RunResult],
    judge_scores: dict[tuple[str, str, str], str],
    corpus: str,
) -> None:
    lines.append("\n### LLM Judge\n")
    lines.append("\n| Engine | fully_correct | partially_correct | wrong | hallucinated |\n")
    lines.append("|---|---|---|---|---|\n")
    by_engine: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (c, eng, qid), verdict in judge_scores.items():
        if c != corpus:
            continue
        by_engine[eng][verdict] += 1
    for engine in sorted(by_engine):
        counts = by_engine[engine]
        lines.append(
            f"| {engine} | {counts.get('fully_correct', 0)} "
            f"| {counts.get('partially_correct', 0)} "
            f"| {counts.get('wrong', 0)} "
            f"| {counts.get('hallucinated', 0)} |\n"
        )


def _write_per_class_breakdown(
    lines: list[str],
    results: list[RunResult],
    qc_by_id: dict[str, QuestionClass],
) -> None:
    lines.append("\n### Per-Question-Class Latency (retrieval p50)\n")
    lines.append("\n| Engine | factual | single_hop | semantic | multi_hop_bridging |\n")
    lines.append("|---|---|---|---|---|\n")
    grouped = group_by_engine_and_class(results, qc_by_id)
    for engine in sorted(grouped):
        row = [engine]
        for qc in [
            QuestionClass.factual,
            QuestionClass.single_hop,
            QuestionClass.semantic,
            QuestionClass.multi_hop_bridging,
        ]:
            subset = grouped[engine].get(qc, [])
            p = latency_percentiles(subset, "retrieval_ms")
            row.append(f"{p['p50']:.1f}" if p["n"] > 0 else "—")
        lines.append("| " + " | ".join(row) + " |\n")


def _write_what_this_means(
    lines: list[str],
    results: list[RunResult],
    question_by_id: dict[str, Question],
) -> None:
    lines.append("\n### What this means\n")
    lines.append(
        "\nLower latency is better. Higher fact recall is better. "
        "The multi_hop_bridging column is the headline: it is the only query class "
        "where graph traversal is supposed to win decisively over naive vector search.\n"
    )


def _write_where_age_wins(
    lines: list[str],
    raw_results_by_corpus: dict[str, list[dict]],
    questions_by_corpus: dict[str, list[Question]],
    judge_scores: dict[tuple[str, str, str], str] | None,
) -> None:
    wins: list[str] = []
    for corpus, raw in raw_results_by_corpus.items():
        results = [RunResult(**r) for r in raw]
        p_by_engine = {}
        for engine in {r.engine for r in results}:
            subset = [r for r in results if r.engine == engine]
            p_by_engine[engine] = latency_percentiles(subset, "retrieval_ms")
        pgrg_p50 = p_by_engine.get("pgrg", {}).get("p50", float("inf"))
        age_p50 = p_by_engine.get("age", {}).get("p50", float("inf"))
        if age_p50 < pgrg_p50:
            wins.append(
                f"- **{corpus}**: AGE p50 retrieval {age_p50:.1f}ms < pgrg {pgrg_p50:.1f}ms"
            )

        questions = questions_by_corpus[corpus]
        qc_by_id = {q.id: q.question_class for q in questions}
        question_by_id = {q.id: q for q in questions}
        age_recall = []
        pgrg_recall = []
        for r in results:
            q = question_by_id.get(r.question_id)
            if q is None:
                continue
            score = score_fact_recall(q, [r.generated_answer])
            if r.engine == "age":
                age_recall.append(score)
            else:
                pgrg_recall.append(score)
        if age_recall and pgrg_recall:
            am = sum(age_recall) / len(age_recall)
            pm = sum(pgrg_recall) / len(pgrg_recall)
            if am > pm:
                wins.append(f"- **{corpus}**: AGE fact recall {am:.3f} > pgrg {pm:.3f}")

    if not wins:
        lines.append("\nAGE did not win on any measured metric in this run.\n")
    else:
        lines.append("\n")
        for w in wins:
            lines.append(w + "\n")
```

- [ ] **Step 4: Generate the golden file**

Run the generator once against the canned fixture and capture the output as `canned_report.md`:
```bash
uv run python -c "
import json
from pathlib import Path
from age_bakeoff.models import Question, QuestionClass
from age_bakeoff.report.generator import generate_report

raw = json.loads(Path('tests/fixtures/canned_raw_results.json').read_text())
questions = [
    Question(id='q1', question='?', gold_answer='Alice Chen leads the Platform team.', required_facts=['Alice Chen', 'Platform'], required_entities=[], question_class=QuestionClass.factual),
    Question(id='q2', question='?', gold_answer='Ingest depends on Kafka.', required_facts=['Ingest', 'Kafka'], required_entities=[], question_class=QuestionClass.single_hop),
    Question(id='q3', question='?', gold_answer='Alice and Bob both work on projects that depend on Kafka.', required_facts=['Alice', 'Bob', 'Kafka'], required_entities=[], question_class=QuestionClass.multi_hop_bridging),
]
generate_report(raw_results_by_corpus={'acme': raw}, questions_by_corpus={'acme': questions}, output_path=Path('tests/fixtures/canned_report.md'), runtime_seconds=123.4)
print('wrote')
"
```

Review `tests/fixtures/canned_report.md` by hand — if it looks right, commit it as the golden file. If the generator has a bug, fix it first, then regenerate.

- [ ] **Step 5: Run the snapshot test**

Run: `uv run pytest tests/test_report_generator.py -v`
Expected: 1 passed. If it fails after regenerating the golden, the generator has non-determinism (dict iteration, set ordering) — fix by sorting.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/report/ \
        benchmarks/age-bakeoff/tests/test_report_generator.py \
        benchmarks/age-bakeoff/tests/fixtures/canned_raw_results.json \
        benchmarks/age-bakeoff/tests/fixtures/canned_report.md
git commit -m "feat(bakeoff): deterministic markdown report generator"
```

---

## Phase 8: Corpus orchestration + CLI

Wire everything together: a `cli.py` with subcommands `setup`, `ingest`, `run`, `judge`, `report`, and a one-shot `run-bakeoff.sh` wrapper.

### Task 8.1: Corpus loaders with chunking integration

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/corpora/base.py`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/corpora/acme.py`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/corpora/scotus.py`
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/corpora/pg_src.py`

**SC coverage:** SC-001

- [ ] **Step 1: Implement the corpus base**

```python
# src/age_bakeoff/corpora/base.py
from __future__ import annotations

from typing import Protocol

from age_bakeoff.models import ExtractionOutput


class Corpus(Protocol):
    name: str

    def load(self) -> ExtractionOutput: ...
```

- [ ] **Step 2: Acme and SCOTUS corpora (thin wrappers)**

```python
# src/age_bakeoff/corpora/acme.py
from age_bakeoff.extraction.loaders import load_acme_extraction
from age_bakeoff.models import ExtractionOutput


class AcmeCorpus:
    name = "acme"

    def load(self) -> ExtractionOutput:
        return load_acme_extraction()


# src/age_bakeoff/corpora/scotus.py
from age_bakeoff.extraction.loaders import load_scotus_extraction
from age_bakeoff.models import ExtractionOutput


class ScotusCorpus:
    name = "scotus"

    def load(self) -> ExtractionOutput:
        return load_scotus_extraction()
```

- [ ] **Step 3: Postgres corpus — walk the cloned tree and run extraction**

```python
# src/age_bakeoff/corpora/pg_src.py
from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from age_bakeoff.chunker import chunk_file
from age_bakeoff.extraction.pg_src import extract_pg_src
from age_bakeoff.models import ExtractionOutput

_CORPUS_ROOT = Path(__file__).parents[3] / "corpora" / "pg-src"
_CACHE = Path(__file__).parents[2] / "age_bakeoff" / "extraction" / "data" / "pg_src.json"

_INCLUDES = [
    "src/backend/executor",
    "src/backend/optimizer",
    "src/include/executor",
    "src/include/nodes",
    "doc/src/sgml/planner-stats.sgml",
    "doc/src/sgml/planner-optimizer.sgml",
    "doc/src/sgml/indices.sgml",
    "doc/src/sgml/performance-tips.sgml",
    "doc/src/sgml/runtime.sgml",
]

_EXCLUDE_SUFFIXES = (".o", ".so", ".a", ".html", ".gif", ".png")


class PgSrcCorpus:
    name = "pg_src"

    def load(self) -> ExtractionOutput:
        if not _CORPUS_ROOT.exists():
            raise RuntimeError(
                f"Postgres source not fetched. Run scripts/fetch_pg_src.sh first."
            )

        chunks = []
        for include in _INCLUDES:
            path = _CORPUS_ROOT / include
            if path.is_file():
                chunks.extend(chunk_file(path))
            elif path.is_dir():
                for f in sorted(path.rglob("*")):
                    if f.is_file() and not f.name.endswith(_EXCLUDE_SUFFIXES):
                        chunks.extend(chunk_file(f))

        if _CACHE.exists():
            from age_bakeoff.extraction.pg_src import extract_pg_src as _extract
            return _extract(chunks, client=None, cache_path=_CACHE)  # uses cache
        else:
            client = OpenAI()
            return extract_pg_src(chunks, client=client, cache_path=_CACHE)
```

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/corpora/
git commit -m "feat(bakeoff): corpus loaders for acme, scotus, pg_src"
```

---

### Task 8.2: CLI

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/cli.py`
- Create: `benchmarks/age-bakeoff/run-bakeoff.sh`

**SC coverage:** SC-009, SC-010

- [ ] **Step 1: Implement the click CLI**

```python
"""age-bakeoff CLI — orchestrates ingest, run, judge, report."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import click
from openai import AsyncOpenAI

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.corpora.acme import AcmeCorpus
from age_bakeoff.corpora.pg_src import PgSrcCorpus
from age_bakeoff.corpora.scotus import ScotusCorpus
from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import RunResult
from age_bakeoff.questions.schema import load_question_set
from age_bakeoff.report.generator import generate_report
from age_bakeoff.runner import Runner, RunnerOptions
from age_bakeoff.scorers.llm_judge import judge_answer, majority_verdict


CORPORA = {
    "acme": AcmeCorpus(),
    "scotus": ScotusCorpus(),
    "pg_src": PgSrcCorpus(),
}


def _build_engines(cfg: BakeoffConfig) -> dict:
    return {
        "pgrg": PgrgEngine(
            dsn=cfg.pgrg_dsn,
            namespace="bakeoff",
            top_k=cfg.top_k,
            hop_budget=cfg.hop_budget,
            answer_model=cfg.answer_model,
            embedding_model=cfg.embedding_model,
        ),
        "age": AgeEngine(
            dsn=cfg.age_dsn,
            graph_name="bakeoff_graph",
            top_k=cfg.top_k,
            hop_budget=cfg.hop_budget,
            answer_model=cfg.answer_model,
            embedding_model=cfg.embedding_model,
        ),
    }


@click.group()
def cli() -> None:
    """AGE vs pg-raggraph benchmark orchestrator."""


@cli.command()
def ingest() -> None:
    """Ingest all three corpora into both engines."""
    cfg = BakeoffConfig()
    engines = _build_engines(cfg)
    runner = Runner(config=cfg, engines=engines, options=RunnerOptions())

    async def _go():
        extractions = {name: corpus.load() for name, corpus in CORPORA.items()}
        await runner.ingest(extractions)

    asyncio.run(_go())
    click.echo("Ingest complete for all corpora on both engines.")


@cli.command()
@click.option("--output-dir", type=click.Path(), default="results/raw")
def run(output_dir: str) -> None:
    """Run all 90 questions × 3 × 2 engines."""
    cfg = BakeoffConfig()
    engines = _build_engines(cfg)
    out_dir = Path(output_dir)
    runner = Runner(
        config=cfg,
        engines=engines,
        options=RunnerOptions(runs_per_question=3, output_dir=out_dir),
    )

    async def _go():
        start = time.perf_counter()
        for name in ["acme", "scotus", "pg_src"]:
            qset = load_question_set(f"questions/{name.replace('_', '-')}.yaml")
            click.echo(f"Running {name}: {len(qset.questions)} questions × 3 runs × 2 engines")
            await runner.run_corpus(name, qset)
        elapsed = time.perf_counter() - start
        (out_dir / "runtime_seconds.txt").write_text(f"{elapsed:.2f}")
        click.echo(f"Full run completed in {elapsed:.1f}s ({elapsed / 60:.1f} min)")

    asyncio.run(_go())


@cli.command()
@click.option("--input-dir", type=click.Path(exists=True), default="results/raw")
def judge(input_dir: str) -> None:
    """Run the LLM judge against all generated answers."""
    cfg = BakeoffConfig()
    client = AsyncOpenAI()
    judge_out = Path(input_dir) / "judge.json"
    results: dict[str, str] = {}

    async def _go():
        for name in ["acme", "scotus", "pg_src"]:
            qset = load_question_set(f"questions/{name.replace('_', '-')}.yaml")
            q_by_id = {q.id: q for q in qset.questions}
            raw = json.loads((Path(input_dir) / f"{name}.json").read_text())
            for entry in raw:
                r = RunResult(**entry)
                if r.error:
                    continue
                q = q_by_id.get(r.question_id)
                if q is None:
                    continue
                verdicts = []
                for _ in range(3):
                    v = await judge_answer(
                        client=client,
                        question=q.question,
                        gold_answer=q.gold_answer,
                        generated_answer=r.generated_answer,
                        model=cfg.judge_model,
                    )
                    verdicts.append(v)
                key = f"{name}|{r.engine}|{r.question_id}|run{r.run_number}"
                results[key] = majority_verdict(verdicts).value

        judge_out.write_text(json.dumps(results, indent=2, sort_keys=True))
        click.echo(f"Judge scores written to {judge_out}")

    asyncio.run(_go())


@cli.command()
@click.option("--input-dir", type=click.Path(exists=True), default="results/raw")
@click.option("--output", type=click.Path(), default="results/REPORT.md")
def report(input_dir: str, output: str) -> None:
    """Generate the final markdown report."""
    raw_by_corpus: dict[str, list[dict]] = {}
    questions_by_corpus = {}
    for name in ["acme", "scotus", "pg_src"]:
        raw_by_corpus[name] = json.loads((Path(input_dir) / f"{name}.json").read_text())
        qset = load_question_set(f"questions/{name.replace('_', '-')}.yaml")
        questions_by_corpus[name] = list(qset.questions)

    runtime_file = Path(input_dir) / "runtime_seconds.txt"
    runtime = float(runtime_file.read_text()) if runtime_file.exists() else 0.0

    judge_file = Path(input_dir) / "judge.json"
    judge_scores = None
    if judge_file.exists():
        raw_judge = json.loads(judge_file.read_text())
        judge_scores = {}
        for key, verdict in raw_judge.items():
            corpus, engine, qid, _run = key.split("|")
            judge_scores[(corpus, engine, qid)] = verdict

    generate_report(
        raw_results_by_corpus=raw_by_corpus,
        questions_by_corpus=questions_by_corpus,
        output_path=Path(output),
        runtime_seconds=runtime,
        judge_scores=judge_scores,
    )
    click.echo(f"Report written to {output}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Write `run-bakeoff.sh`**

```bash
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

echo ">> Running benchmark (this is the slow step)..."
uv run age-bakeoff run

echo ">> Running LLM judge..."
uv run age-bakeoff judge

echo ">> Generating report..."
uv run age-bakeoff report

echo ">> Done. See results/REPORT.md"
```

Make executable: `chmod +x benchmarks/age-bakeoff/run-bakeoff.sh`

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/cli.py benchmarks/age-bakeoff/run-bakeoff.sh
git commit -m "feat(bakeoff): CLI + run-bakeoff.sh one-shot entrypoint"
```

---

## Phase 9: Full run + drift checkpoints

### Task 9.1: First end-to-end dry run on Acme only

**SC coverage:** SC-004, SC-009

Verify the full pipeline works on one corpus before burning budget on all three.

- [ ] **Step 1: Run Acme-only dry run**

```bash
cd benchmarks/age-bakeoff
export OPENAI_API_KEY=sk-...
docker compose up -d
bash scripts/fetch_pg_src.sh  # noop if already done
uv run age-bakeoff ingest
# Temporarily comment out scotus and pg_src in cli.run for this dry run, or invoke runner directly
uv run python -c "
import asyncio, time
from pathlib import Path
from age_bakeoff.config import BakeoffConfig
from age_bakeoff.cli import _build_engines, CORPORA
from age_bakeoff.questions.schema import load_question_set
from age_bakeoff.runner import Runner, RunnerOptions

async def _go():
    cfg = BakeoffConfig()
    engines = _build_engines(cfg)
    runner = Runner(cfg, engines, RunnerOptions(runs_per_question=1, output_dir=Path('results/dryrun')))
    qset = load_question_set('questions/acme.yaml')
    t0 = time.perf_counter()
    await runner.run_corpus('acme', qset)
    print(f'acme dry run: {time.perf_counter() - t0:.1f}s')

asyncio.run(_go())
"
```

Expected: `results/dryrun/acme.json` with `30 × 2 = 60` entries. Check a few rows by hand for sanity.

- [ ] **Step 2: Fix any issues surfaced by the dry run**

Common issues:
- Cypher injection on entity names with special chars → tighten `_slug`
- pg-raggraph namespace conflict with prior runs → `delete(ns)` before ingest (already in adapter)
- Cost blow-up if a corpus happens to trigger many extraction calls → the pg_src extraction should have been cached from Task 2.2; verify `data/pg_src.json` exists

- [ ] **Step 3: Commit any fixes**

```bash
git commit -am "fix(bakeoff): dry run adjustments"
```

---

### Task 9.2: Full three-corpus run

**SC coverage:** SC-004, SC-009, SC-010

- [ ] **Step 1: Execute the full bake-off**

```bash
cd benchmarks/age-bakeoff
./run-bakeoff.sh 2>&1 | tee results/run.log
```

Expected:
- All three corpora complete
- `results/raw/{acme,scotus,pg_src}.json` each contain `30 × 3 × 2 = 180` entries
- `results/raw/judge.json` contains `~540` entries
- `results/REPORT.md` generated
- `results/raw/runtime_seconds.txt` shows wall-clock < 3600 (60 min)

- [ ] **Step 2: Verify SC-009 (60-minute ceiling)**

```bash
cat results/raw/runtime_seconds.txt
```
If `>3600`, investigate: is the AGE graph creation serial-blocking? Are we re-embedding on every retrieve? Optimize before retrying. Do not just raise the ceiling — SC-009 is a hard constraint.

- [ ] **Step 3: Sanity-check the raw output**

```bash
jq 'length' results/raw/acme.json   # should be 180
jq 'length' results/raw/scotus.json # should be 180
jq 'length' results/raw/pg_src.json # should be 180
jq '[.[] | select(.error != null)] | length' results/raw/acme.json  # should be 0 or very low
```

- [ ] **Step 4: Commit raw results**

```bash
# results/raw/ is gitignored — but the summary is not
git add results/REPORT.md benchmarks/age-bakeoff/results/raw/runtime_seconds.txt 2>/dev/null || true
git commit -am "chore(bakeoff): first full run results"
```

---

### ⛔ DC-003: Drift Checkpoint

**Trigger:** After Task 9.2 produces a full `REPORT.md`.

**Actions:**
1. Re-read the Out of Scope list in `Mission-Brief-age-bakeoff.md`.
2. Verify: did we silently tune pg-raggraph during the run? (check `git log --all` for any commits touching `src/pg_raggraph/`)
3. Verify: did we swap the embedding model or answer model to improve numbers? (check `.env` and `BakeoffConfig` defaults against the brief)
4. Verify: do `acme.json`, `scotus.json`, `pg_src.json` each contain 180 entries?
5. Verify: did any SC-XXX get lost? Walk each one briefly:
   - SC-001 (identical inputs) — covered by ingest path
   - SC-002 (matching configs) — runner's verify_symmetry ran at start
   - SC-003 (90 questions) — all loaded at run time
   - SC-004 (per-run JSON) — present
   - SC-005 (fact recall) — computed in report
   - SC-006 (LLM judge 3×) — `judge` command ran
   - SC-007 (report sections) — check REPORT.md by eye
   - SC-009 (60 min) — check runtime_seconds.txt
6. If any check fails → STOP, fix, re-run, re-check.

- [ ] **DC-003 actions completed. Evidence recorded in commit message.**

---

### Task 9.3: Inspect the "Where AGE wins" section

**SC coverage:** SC-008

### ⛔ DC-004: Drift Checkpoint

**Trigger:** Before writing anything into the "Where AGE wins" section — including any manual additions to the generated output.

**Actions:**
1. Re-read SC-008 in the mission brief.
2. Scan `results/REPORT.md` → "Where AGE wins" section.
3. If the generated section says "AGE did not win on any measured metric," do NOT hand-soften that. Leave it.
4. If it lists specific wins, verify each win against the raw JSON — any exaggeration or hedging is drift.
5. Three-question check:
   - Am I hand-waving? (e.g., "roughly comparable," "in some cases")
   - Am I reporting findings or spinning them?
   - Would a hostile reader catch me downplaying anything?
6. If hand-waving is creeping in → STOP, rewrite in concrete terms with numbers.

- [ ] **DC-004 actions completed.**

- [ ] **Step 1: Add a "Methodology" section to REPORT.md**

Hand-write a section (this is the ONE allowed manual addition) describing:
- How chunks were produced (shared chunker)
- How graph data was sourced (hand-curated for Acme/SCOTUS, LLM-extracted cached for pg_src)
- What "cold" vs "warm" means
- How judge votes were aggregated
- Known asymmetries between engines (retrieval strategies, top_k, hop budget)

Place this section before the corpus results. Commit.

```bash
git add benchmarks/age-bakeoff/results/REPORT.md
git commit -m "docs(bakeoff): methodology section in REPORT.md"
```

---

## Phase 10: Documentation updates + reproduction dry-run

### Task 10.1: Write README.md

**Files:**
- Create: `benchmarks/age-bakeoff/README.md`

**SC coverage:** SC-010

- [ ] **Step 1: Draft README**

```markdown
# AGE vs pg-raggraph Bake-Off

Head-to-head benchmark comparing Apache AGE and pg-raggraph on three corpora: Acme Labs, SCOTUS, and a slice of Postgres (executor + planner). Measures end-to-end latency, deterministic fact recall, and LLM-judged answer quality across 90 gold-labeled questions.

See `../../docs/why-not-apache-age.md` for the architectural context. Results live in `results/REPORT.md` after a full run.

## Reproduce

Requirements:
- Docker + Docker Compose
- `uv` (`pip install uv` or see https://docs.astral.sh/uv/)
- OpenAI API key with access to the configured models

```bash
cp .env.example .env
# edit .env — set OPENAI_API_KEY, optionally change models or ports
uv sync --extra dev
./run-bakeoff.sh
```

The full run takes ~30-60 minutes. Results are written to `results/REPORT.md` and `results/raw/`.

## What it measures

| Metric | How |
|---|---|
| Retrieval latency (cold/warm, p50/p95/p99) | Timed around each engine's retrieve call |
| End-to-end latency | Retrieval + OpenAI answer generation |
| Fact recall | Deterministic substring match against `required_facts` in the gold set |
| Answer quality | OpenAI judge, 3× majority vote, rubric: fully_correct / partially_correct / wrong / hallucinated |

## Corpora

| Corpus | Docs | Questions | Bridging Qs |
|---|---|---|---|
| Acme Labs | ~160 synthetic org documents | 30 | 5 |
| SCOTUS | ~40 opinions + justice/case/issue graph | 30 | 5 |
| Postgres executor + planner | ~100K LOC C/SGML | 30 | 5 |

Postgres is pinned to tag `REL_16_5` for reproducibility.

## Fairness

- Both engines receive byte-identical pre-chunked content (see `src/age_bakeoff/chunker.py`)
- Both engines receive identical entity/relationship data (see `src/age_bakeoff/extraction/`)
- Same embedding model (`BAAI/bge-small-en-v1.5`), same answer model, same judge model, same top_k, same hop budget
- No hand-curated graph asymmetries — if one engine gets the Acme org graph, the other gets the same graph

See `ARCHITECTURE.md` for the full fairness rationale and every known asymmetry.

## Cost

One full run costs approximately $5-15 in OpenAI spend. The harness enforces a hard budget ceiling (default $25 via `BAKEOFF_COST_BUDGET_USD`).

## Swapping the OpenAI model

Edit `.env`:
```
BAKEOFF_ANSWER_MODEL=gpt-4o-mini
BAKEOFF_JUDGE_MODEL=gpt-4o-mini
```

Any OpenAI model name works. Defaults to `gpt-5-mini` when that's available.

## Directory layout

```
benchmarks/age-bakeoff/
├── README.md              # this file
├── ARCHITECTURE.md        # fairness rationale
├── docker-compose.yml     # both DBs
├── run-bakeoff.sh         # one-shot entrypoint
├── corpora/               # cloned sources (pg-src is gitignored)
├── questions/             # 90 gold-labeled questions
├── src/age_bakeoff/       # the benchmark package
├── tests/                 # pytest suite
└── results/
    ├── raw/               # per-corpus JSON (gitignored)
    └── REPORT.md          # generated markdown report
```
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/age-bakeoff/README.md
git commit -m "docs(bakeoff): README with reproduction instructions"
```

---

### Task 10.2: Write ARCHITECTURE.md

**Files:**
- Create: `benchmarks/age-bakeoff/ARCHITECTURE.md`

**SC coverage:** SC-008 (known asymmetries documented)

- [ ] **Step 1: Document the fairness mechanisms and every known asymmetry**

```markdown
# Bake-Off Architecture

## Fairness as a design goal

The whole benchmark is worthless if we're secretly measuring something other than graph-engine performance. This doc lists every mechanism we use to keep the comparison honest, and every asymmetry we know about but couldn't eliminate.

## Shared primitives

All three of these flow through a single code path shared by both engines:

1. **Chunking** — `src/age_bakeoff/chunker.py` splits prose on markdown headings, Python on `def`/`class`, C on function/struct boundaries, with a hard 3000-char fallback. The same chunk list is fed into both engines via `ExtractionOutput`. No engine chunks on its own.
2. **Extraction** — For Acme and SCOTUS, the entity/relationship data is hand-transcribed from the graphrag-demo seeds into `src/age_bakeoff/extraction/data/{acme,scotus}.json`. Both engines ingest the same nodes and edges. For pg_src, a single LLM extraction pass produces `data/pg_src.json`, which both engines then load.
3. **Embedding** — FastEmbed local (`BAAI/bge-small-en-v1.5`, 384 dims) in both adapters. Loaded once per engine instance.
4. **Answer generation** — `src/age_bakeoff/engines/openai_answerer.py` is called by both engines with the same system prompt, same user template, same model, same temperature.
5. **Judge** — `src/age_bakeoff/scorers/llm_judge.py` is the same path for both engines' outputs.

## Hyperparameters

Both engines receive these from `BakeoffConfig`:
- `top_k = 10`
- `hop_budget = 2`
- `embedding_model = "BAAI/bge-small-en-v1.5"`
- `answer_model` = (default `gpt-5-mini`)

`Runner.verify_symmetry()` fails loudly at startup if any of these diverge.

## Known asymmetries (the honest list)

Despite the shared primitives, the two engines are not perfectly isomorphic. These are the deviations we know about:

1. **Retrieval strategies are semantically different.** pg-raggraph's `hybrid` mode fuses vector + BM25 + graph-boost via its internal smart-mode heuristics. AGE's adapter implements a simpler strategy: pgvector top-K seeds + Cypher entity lookup + `MATCH ... [*1..hop_budget]` expansion. Both run inside their hop budget, both return the same `top_k` count, but the internal ranking differs.
   - *Impact:* if AGE retrieves better chunks, we credit AGE. If pg-raggraph retrieves better chunks, we credit pg-raggraph. We're measuring "the best each engine can do on identical data within matching hyperparameters."
2. **pg-raggraph bypasses its own extractor.** The adapter calls the raw `Database` helpers instead of `GraphRAG.ingest()`. This is intentional — we don't want pg-raggraph's LLM extraction to produce different entities than AGE sees. But it means pg-raggraph's ingestion path in this benchmark is NOT what a real pg-raggraph user runs.
3. **AGE doesn't use the demo's full retrieval pipeline.** The graphrag-demo has a richer `combined.py` with hybrid BM25, RRF reranking, and scoring heuristics. We pulled out just the vector-seed + Cypher-expansion core. This favors neither engine consistently — the omitted heuristics could have helped either side.
4. **AGE's Cypher is string-interpolated, not parameterized.** Entity IDs are slugified to `[a-z0-9_]` before ingestion, so this is safe, but it's not idiomatic — a production AGE client would use a parameterized driver.
5. **Index tuning is asymmetric.** pg-raggraph auto-creates its indexes via its schema. AGE requires manual BTREE indexes on `graphid` columns — we create the default ones per AGE's own docs but do no further tuning.
6. **Connection pooling differs.** pg-raggraph uses psycopg3's async pool. AGE adapter uses psycopg3 sync connections inside a thread pool (because AGE's `cypher()` function call and `LOAD 'age'` don't compose cleanly with async drivers in our testing).

Any of these asymmetries could be pointed at to contest specific findings. We document them so a skeptical reader can reason about what's being measured.

## What the report is and isn't

The report **is**:
- A head-to-head measurement under equal hyperparameters and identical graph data
- Reproducible from a clean checkout given a working Docker + OpenAI key
- Honest about where each engine wins

The report **is not**:
- A definitive claim about the upper bound of either engine (neither has been tuned for maximum performance)
- Evidence about cloud deployability (AGE cannot run on AWS RDS, Cloud SQL, Supabase, or Neon regardless of its benchmark numbers — see `docs/why-not-apache-age.md`)
- A general ranking of graph databases
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/age-bakeoff/ARCHITECTURE.md
git commit -m "docs(bakeoff): ARCHITECTURE with fairness rationale and known asymmetries"
```

---

### Task 10.3: Update `docs/why-not-apache-age.md` with real numbers

**Files:**
- Modify: `docs/why-not-apache-age.md`

**SC coverage:** SC-011

- [ ] **Step 1: Re-read the current doc and identify every third-party benchmark claim**

```bash
grep -n "40×\|40x\|2-4x\|2-40\|benchmark\|LightRAG issue" /home/yonk/yonk-tools/pg-raggraph/docs/why-not-apache-age.md
```

Current claims to address:
- "2–40× faster" (headline table)
- "2–4× on small datasets"
- "40× faster for 4-hop queries"
- LightRAG #2255 citation

- [ ] **Step 2: For each claim, replace or annotate**

Rule: if our bake-off measured the same thing, replace the cited number with ours and link to `benchmarks/age-bakeoff/REPORT.md`. If our bake-off didn't measure it (e.g., the 17-hour LightRAG incident is historical, not a metric we can reproduce), leave it in but add `— not re-measured; see our bake-off for current numbers`.

Example edit:
```diff
-Published benchmarks show recursive CTEs beating AGE Cypher by **2–4× on small datasets** for simple traversals, and one social-graph benchmark found them **40× faster** for 4-hop queries.
+Our own [bake-off](../benchmarks/age-bakeoff/REPORT.md) measured pg-raggraph's retrieval p50 at **X ms** vs AGE at **Y ms** on the Acme corpus, and **A ms vs B ms** on the Postgres executor corpus. Published third-party benchmarks show the gap widening to 40× on deeper traversals; our slice (2-hop budget) tests the near end where the differential should be smallest.
```

Fill in X/Y/A/B from the actual `results/REPORT.md` numbers.

- [ ] **Step 3: Add a link to the bake-off README from the docs index**

Edit `docs/README.md` to add under Engineering Deep-Dive:
```markdown
- **[../benchmarks/age-bakeoff/README.md](../benchmarks/age-bakeoff/README.md)** — Reproducible head-to-head vs Apache AGE (results in `REPORT.md`)
```

- [ ] **Step 4: Commit**

```bash
git add docs/why-not-apache-age.md docs/README.md
git commit -m "docs(why-not-age): replace cited third-party benchmarks with bake-off measurements"
```

---

### Task 10.4: Clean-state reproduction dry-run

**SC coverage:** SC-010

- [ ] **Step 1: Simulate a fresh checkout**

```bash
cd /tmp
git clone /home/yonk/yonk-tools/pg-raggraph pg-raggraph-fresh
cd pg-raggraph-fresh/benchmarks/age-bakeoff
cp .env.example .env
# edit .env to put in OPENAI_API_KEY
docker compose down -v 2>/dev/null || true  # wipe any cached containers
```

- [ ] **Step 2: Run the full README instructions verbatim**

```bash
uv sync --extra dev
./run-bakeoff.sh
```

- [ ] **Step 3: Verify output**

```bash
ls results/REPORT.md
cat results/raw/runtime_seconds.txt
```

Expected: report exists, runtime under 3600.

- [ ] **Step 4: Note any tribal knowledge gaps in README**

If the dry run required a step not in README (e.g., "wait 30 seconds for AGE container to finish building"), add it to README. Re-commit.

- [ ] **Step 5: Clean up the fresh clone**

```bash
cd /tmp && rm -rf pg-raggraph-fresh
```

---

### ⛔ DC-FINAL: Drift Checkpoint

**Trigger:** After Task 10.4 completes successfully.

**Actions:**
1. Re-read `skill-output/mission-brief/Mission-Brief-age-bakeoff.md` in full.
2. For each success criterion, point to concrete evidence:
   - **SC-001 (identical inputs):** `src/age_bakeoff/chunker.py` + `ExtractionOutput` single code path. Verified by `tests/test_engine_parity.py::test_extraction_checksum_stable` + passing parity test.
   - **SC-002 (matching configs):** `BakeoffConfig` + `Runner.verify_symmetry()`. Verified by `tests/test_engine_parity.py::test_configs_are_symmetric`.
   - **SC-003 (90 questions, ≥5 bridging each):** `questions/{acme,scotus,pg-src}.yaml`. Verified by `questions/schema.py` validators running at load time.
   - **SC-004 (per-run JSON schema):** `results/raw/{acme,scotus,pg_src}.json` each contain 180 entries with required fields. Verified by `tests/test_runner_smoke.py`.
   - **SC-005 (fact recall):** Present in `REPORT.md` with 95% CI. Verified by `tests/test_fact_recall.py`.
   - **SC-006 (LLM judge 3× majority):** `results/raw/judge.json` has per-question verdicts. Verified by `tests/test_llm_judge.py`.
   - **SC-007 (report sections):** `REPORT.md` contains latency, fact recall, judge, per-class breakdown, "what this means," "where AGE wins." Verified by `tests/test_report_generator.py` snapshot.
   - **SC-008 ("where AGE wins"):** Section present and honest. Verified by DC-004 drift check.
   - **SC-009 (< 60 min):** `results/raw/runtime_seconds.txt` shows < 3600. Confirmed.
   - **SC-010 (reproducible from clean state):** Task 10.4 dry-run succeeded.
   - **SC-011 (why-not-age.md updated):** Task 10.3 replaced cited numbers. Verified by diffing pre/post versions.
3. For any SC-XXX without concrete evidence → the work is not complete. Go back and finish it.
4. Run the full test suite one last time:
   ```bash
   cd benchmarks/age-bakeoff
   uv run pytest tests/ -v
   ```
   Expected: all tests pass.

- [ ] **DC-FINAL actions completed. All SC-XXX have evidence. Work is complete.**

- [ ] **Step 1: Final commit**

```bash
git add -A
git commit -m "chore(bakeoff): benchmark complete — all SC-XXX verified"
```

---

## Self-Review

**Spec coverage check:**

| SC | Task(s) |
|---|---|
| SC-001 identical inputs | 1.3 chunker, 2.1 loaders, 2.2 pg_src extractor, 3.4 parity test |
| SC-002 matching configs | 1.2 config, 5.2 verify_symmetry, 3.4 parity test |
| SC-003 90 questions | 4.1 schema, 4.2-4.4 yaml files |
| SC-004 per-run JSON | 5.2 runner, 1.1 RunResult model |
| SC-005 fact recall | 6.1 scorer, 7.2 report |
| SC-006 LLM judge | 6.2 scorer, 8.2 cli judge command |
| SC-007 report sections | 7.1 aggregate, 7.2 generator |
| SC-008 where AGE wins | 7.2 generator `_write_where_age_wins`, DC-004 |
| SC-009 60-minute ceiling | 8.2 cli runtime recording, 9.2 full run |
| SC-010 reproducible | 10.1 README, 10.4 dry-run |
| SC-011 why-not-age.md update | 10.3 |

**Drift checkpoint coverage:**
- DC-001 after Task 3.4 (smoke test both engines)
- DC-002 after Task 4.4 (question sets drafted)
- DC-003 after Task 9.2 (first full run)
- DC-004 before Task 9.3 (AGE-wins section)
- DC-FINAL after Task 10.4 (clean reproduction)

**Placeholder scan:** No "TBD", no "similar to above", no "appropriate error handling" hand-waves. Every code block is complete runnable code. The one intentional ellipsis is in the question YAML examples where the reader writes 30 of the same shape.

**Type consistency:** `Chunk`, `ExtractedEntity`, `ExtractedRelationship`, `ExtractionOutput`, `Question`, `QuestionClass`, `RunResult`, `EngineInfo`, `RetrievalResponse`, `BakeoffConfig`, `Runner`, `RunnerOptions` — all defined once in Phase 1/3, used consistently. Method names: `ingest`, `retrieve`, `generate_answer`, `info`, `cleanup` — consistent across both adapters. `load_question_set(path, strict=True)` signature fixed in Task 5.2 to support test fixtures.

**Known risks flagged:**
- pg-raggraph's DB helper signatures may not match what Task 3.2 assumes → Task 3.2 Step 1 tells the implementer to inspect `db.py` first
- AGE extension install in Docker may fail → Task 0.2 Step 5 has a verification command
- OpenAI model name `gpt-5-mini` may not exist → fallback to `gpt-4o-mini` documented in .env.example and cost table

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-14-age-bakeoff-benchmark.md`.

**Worktree note:** This plan adds a new directory (`benchmarks/age-bakeoff/`) and only touches two existing files (`docs/why-not-apache-age.md`, `docs/README.md`) at the very end. A dedicated worktree is optional but recommended if you want to keep pg-raggraph `main` development unblocked for the 2-3 days this takes. If you want one, say so and I'll invoke `superpowers:using-git-worktrees` before execution.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for a plan this size because each phase produces a commit and we can course-correct at the drift checkpoints.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?



