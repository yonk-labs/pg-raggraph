# Chunkshop — Reusable Ingestion Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **REPO MOVE (2026-04-19, after Task 1):** chunkshop was extracted to a standalone
> monorepo at `/home/yonk/yonk-tools/chunkshop/` with `python/`, `rust/`, `go/` subdirs.
> The pg-raggraph bakeoff consumes it as a uv path dependency
> (`chunkshop = { path = "../../../chunkshop/python", editable = true }`).
> Path translations for Tasks 2–11:
> - `benchmarks/age-bakeoff/scripts/chunkshop/**` → `python/src/chunkshop/**` in the chunkshop repo
> - `benchmarks/age-bakeoff/tests/chunkshop/**` → `python/tests/chunkshop/**` (no `__init__.py`)
> - `benchmarks/age-bakeoff/scripts/chunkshop/configs/**` → `python/src/chunkshop/configs/**`
> - commit from `/home/yonk/yonk-tools/chunkshop/`
> Task 12 (`factorial-probe-query.py`) stays in pg-raggraph — it's the experiment-specific
> consumer that imports chunkshop. Task 3's `sentence_aware` chunker must NOT import
> `age_bakeoff.chunker`; port the logic into chunkshop directly (same behavior).

**Goal:** Build a reusable, config-driven ingestion tool (`chunkshop`) that pulls text from multiple source types, chunks it, embeds it, optionally tags it, and lands the result in a pgvector table — then use it to run the 12-cell factorial chunking × embedding experiment on scotus.

**Architecture:** Plugin-shaped Python package with protocol-based adapters for 4 concerns (Source, Chunker, Embedder, Extractor) and a single Sink (pgvector). A YAML config describes one (source, chunker, embedder, extractor, target) "cell" end-to-end. A single-cell CLI (`ingest`) runs one YAML; an orchestrator CLI (`orchestrate`) runs N YAMLs in parallel with checkpoint polling. The factorial experiment is expressed as 12 YAML files in `configs/factorial/`.

**Tech Stack:** Python 3.12, click, pydantic v2, pyyaml, fastembed, psycopg (sync connection for simplicity; the tool is a batch ingester, not a live service), numpy, rake-nltk (optional extractor). No async, no orm. Runs under the bakeoff's existing uv env.

---

## Scope and Boundaries

**In scope:**
- Single package `chunkshop/` under `benchmarks/age-bakeoff/scripts/chunkshop/`
- Sources: `files` (glob), `json_corpus` (scotus.json-style), `pg_table` (reads id+text cols from existing table). S3 and HTTP implemented as typed stubs raising `NotImplementedError` so the protocol is visible.
- Chunkers: `sentence_aware` (wraps `age_bakeoff.chunker.chunk_text`), `fixed_overlap`, `hierarchy`, `neighbor_expand` (post-processes another chunker)
- Embedders: `fastembed` with any HF model name
- Extractors: `none` (default), `rake_keywords` (local, no LLM)
- Sink: pgvector table creation + per-doc upsert in `factorial` schema (or any schema specified in YAML)
- Orchestrator: pool-of-4 default, per-worker CPU pinning via `OMP_NUM_THREADS`, checkpoint polling at 60/120/300/600s
- 12 factorial YAML configs + smoke-then-full run
- Probe-query tool that reads the 12 tables and reports retrieval metrics for 4 scotus probes

**Out of scope:**
- Live/streaming ingest (batch only)
- LLM-based extraction (noun-phrase/keyword extraction only, local)
- Incremental / delta ingest (each run truncates or creates the target table)
- Multi-tenant namespace logic (each YAML targets one table)
- Migration system for target table schema changes
- pg-raggraph integration (the tool writes pgvector tables; pg-raggraph's own ingest path is unchanged)

## Constraints (Always / Ask First / Never)

**Always:**
- Pin `OMP_NUM_THREADS=1` by default for each worker (override via CLI/YAML)
- Write per-cell progress to `logs/{cell_name}.log` with a heartbeat every N docs
- Use per-doc transactions (one doc = one `INSERT ... RETURNING` txn) so partial progress is visible via `SELECT COUNT(DISTINCT doc_id)`
- Record the exact config that produced a table by storing it as a JSON blob in `factorial.cell_metadata` on completion

**Ask first:**
- Adding S3 or HTTP source adapters (currently out of scope; stubs only)
- Adding LLM extraction (extractors must be local)
- Changing target DB (current plan: pgrg at `localhost:5434`)

**Never:**
- Write LLM calls into the default codepath ($0 budget; extractor `none` is the default)
- Truncate an existing `factorial.*` table without `--overwrite` flag
- Drop the `factorial` schema without explicit confirmation
- Commit real PG passwords — use `DSN` env var or CLI flag

## File Structure

```
benchmarks/age-bakeoff/scripts/chunkshop/
├── __init__.py                     # Package marker, re-exports main types
├── cli.py                          # Click CLI: ingest, orchestrate, init-schema
├── config.py                       # Pydantic models: CellConfig, SourceConfig, ChunkerConfig, etc.
├── runner.py                       # Single-cell runner: wires source → chunker → embedder → extractor → sink
├── orchestrator.py                 # Parallel orchestration with checkpoint polling
├── sources/
│   ├── __init__.py                 # Registry: load_source(cfg) -> Source
│   ├── base.py                     # Source Protocol + Document dataclass
│   ├── files.py                    # FilesSource (glob + optional id-from-path)
│   ├── json_corpus.py              # JsonCorpusSource (scotus.json-style)
│   ├── pg_table.py                 # PgTableSource (reads id+text cols)
│   ├── http.py                     # HttpSource (stub, NotImplementedError)
│   └── s3.py                       # S3Source (stub, NotImplementedError)
├── chunkers/
│   ├── __init__.py                 # Registry: load_chunker(cfg) -> Chunker
│   ├── base.py                     # Chunker Protocol + Chunk dataclass
│   ├── sentence_aware.py           # SentenceAwareChunker (wraps age_bakeoff.chunker)
│   ├── fixed_overlap.py            # FixedOverlapChunker
│   ├── hierarchy.py                # HierarchyChunker (md heading prefix)
│   └── neighbor_expand.py          # NeighborExpandChunker (post-processes another)
├── embedders/
│   ├── __init__.py                 # Registry: load_embedder(cfg) -> Embedder
│   ├── base.py                     # Embedder Protocol
│   └── fastembed_provider.py       # FastembedProvider
├── extractors/
│   ├── __init__.py                 # Registry: load_extractor(cfg) -> Extractor
│   ├── base.py                     # Extractor Protocol
│   ├── none_provider.py            # NoneExtractor (returns [])
│   └── rake_keywords.py            # RakeKeywordsExtractor
├── sink.py                         # PgVectorSink: create table, upsert chunks
├── README.md                       # Usage doc with example YAMLs
└── configs/
    ├── example-files-to-bge.yaml   # Documented example for end users
    └── factorial/                  # Our experiment
        ├── A-bge-small.yaml
        ├── A-bge-base.yaml
        ├── A-nomic.yaml
        ├── B-bge-small.yaml
        ├── B-bge-base.yaml
        ├── B-nomic.yaml
        ├── C-bge-small.yaml
        ├── C-bge-base.yaml
        ├── C-nomic.yaml
        ├── D-bge-small.yaml
        ├── D-bge-base.yaml
        └── D-nomic.yaml
benchmarks/age-bakeoff/tests/chunkshop/
├── __init__.py
├── test_config.py
├── test_sources_files.py
├── test_sources_json_corpus.py
├── test_chunkers.py                # all 4 chunkers
├── test_embedder_fastembed.py
├── test_extractor_rake.py
├── test_sink.py                    # requires PG at 5434
├── test_runner.py
└── test_orchestrator.py
benchmarks/age-bakeoff/scripts/
└── factorial-probe-query.py        # Reads from 12 tables, runs 4 probes, writes report
```

**Existing files we supersede (delete after tool works):**
- `benchmarks/age-bakeoff/scripts/factorial-probe.py` (in-memory; crashed on bge-small)
- `benchmarks/age-bakeoff/tests/test_factorial_probe.py` (tests for the superseded script)

---

## Task 1: Package skeleton + config model

**Files:**
- Create: `benchmarks/age-bakeoff/scripts/chunkshop/__init__.py`
- Create: `benchmarks/age-bakeoff/scripts/chunkshop/config.py`
- Create: `benchmarks/age-bakeoff/tests/chunkshop/__init__.py`
- Create: `benchmarks/age-bakeoff/tests/chunkshop/test_config.py`

- [ ] **Step 1: Write failing tests for config loading**

```python
# tests/chunkshop/test_config.py
import textwrap
import pytest
from chunkshop.config import CellConfig, load_config


def test_loads_minimal_yaml(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: test_a_bge_small
        source:
          type: json_corpus
          path: /data/scotus.json
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: BAAI/bge-small-en-v1.5
          dim: 384
        target:
          dsn_env: AGE_BAKEOFF_PGRG_DSN
          schema: factorial
          table: test_a_bge_small
        """))
    cfg = load_config(yaml)
    assert cfg.cell_name == "test_a_bge_small"
    assert cfg.source.type == "json_corpus"
    assert cfg.embedder.dim == 384
    assert cfg.target.table == "test_a_bge_small"
    assert cfg.extractor.type == "none"  # default
    assert cfg.runtime.omp_num_threads == 1  # default
    assert cfg.runtime.doc_limit is None  # default: all docs


def test_rejects_unknown_source_type(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: bad
        source:
          type: ftp
          url: ftp://bad
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: x
          dim: 1
        target:
          dsn_env: X
          schema: factorial
          table: bad
        """))
    with pytest.raises(ValueError, match="ftp"):
        load_config(yaml)


def test_table_name_validated(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: bad_table
        source: {type: json_corpus, path: /x}
        chunker: {type: sentence_aware}
        embedder: {type: fastembed, model_name: x, dim: 1}
        target:
          dsn_env: X
          schema: factorial
          table: "weird name!"
        """))
    with pytest.raises(ValueError, match="table"):
        load_config(yaml)
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd benchmarks/age-bakeoff && uv run pytest tests/chunkshop/test_config.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `config.py`**

```python
# scripts/chunkshop/config.py
"""Pydantic config models for chunkshop cells."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilesSource(_Base):
    type: Literal["files"]
    glob: str
    id_from: Literal["path", "stem", "sha1"] = "stem"
    encoding: str = "utf-8"


class JsonCorpusSource(_Base):
    type: Literal["json_corpus"]
    path: str
    documents_key: str = "documents"
    id_field: str = "id"
    content_field: str = "content"
    title_field: Optional[str] = "title"


class PgTableSource(_Base):
    type: Literal["pg_table"]
    dsn_env: str
    schema_name: str = Field(alias="schema")
    table: str
    id_column: str
    content_column: str
    title_column: Optional[str] = None
    where: Optional[str] = None


class HttpSource(_Base):
    type: Literal["http"]
    urls: list[str] = Field(default_factory=list)
    sitemap: Optional[str] = None


class S3Source(_Base):
    type: Literal["s3"]
    bucket: str
    prefix: str = ""


SourceConfig = Annotated[
    Union[FilesSource, JsonCorpusSource, PgTableSource, HttpSource, S3Source],
    Field(discriminator="type"),
]


class SentenceAwareChunker(_Base):
    type: Literal["sentence_aware"] = "sentence_aware"
    doc_type: Literal["prose", "code"] = "prose"


class FixedOverlapChunker(_Base):
    type: Literal["fixed_overlap"]
    window_words: int = 300
    step_words: int = 150


class HierarchyChunker(_Base):
    type: Literal["hierarchy"]
    prefix_heading: bool = True
    min_section_chars: int = 100


class NeighborExpandChunker(_Base):
    type: Literal["neighbor_expand"]
    base: "ChunkerConfig"
    window: int = 1  # seq ± window


ChunkerConfig = Annotated[
    Union[SentenceAwareChunker, FixedOverlapChunker, HierarchyChunker, NeighborExpandChunker],
    Field(discriminator="type"),
]
NeighborExpandChunker.model_rebuild()


class FastembedEmbedder(_Base):
    type: Literal["fastembed"]
    model_name: str
    dim: int
    batch_size: int = 64


EmbedderConfig = Annotated[Union[FastembedEmbedder], Field(discriminator="type")]


class NoneExtractor(_Base):
    type: Literal["none"] = "none"


class RakeKeywordsExtractor(_Base):
    type: Literal["rake_keywords"]
    top_k: int = 10
    min_chars: int = 3


ExtractorConfig = Annotated[
    Union[NoneExtractor, RakeKeywordsExtractor], Field(discriminator="type")
]


class TargetConfig(_Base):
    dsn_env: str = "AGE_BAKEOFF_PGRG_DSN"
    schema_name: str = Field(alias="schema")
    table: str
    overwrite: bool = False  # drop+recreate if table exists
    hnsw: bool = True

    @field_validator("table", "schema_name")
    @classmethod
    def _safe_ident(cls, v: str) -> str:
        if not re.match(r"^[a-z_][a-z0-9_]*$", v):
            raise ValueError(f"table/schema must match ^[a-z_][a-z0-9_]*$, got {v!r}")
        return v


class RuntimeConfig(_Base):
    omp_num_threads: int = 1
    doc_limit: Optional[int] = None
    log_path: Optional[str] = None
    heartbeat_every: int = 25


class CellConfig(_Base):
    cell_name: str
    source: SourceConfig
    chunker: ChunkerConfig
    embedder: EmbedderConfig
    extractor: ExtractorConfig = NoneExtractor()
    target: TargetConfig
    runtime: RuntimeConfig = RuntimeConfig()


def load_config(path: str | Path) -> CellConfig:
    data = yaml.safe_load(Path(path).read_text())
    return CellConfig(**data)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `cd benchmarks/age-bakeoff && uv run pytest tests/chunkshop/test_config.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Create `__init__.py` stubs**

```python
# scripts/chunkshop/__init__.py
"""Reusable ingestion tool: source -> chunker -> embedder -> extractor -> pgvector table."""
from chunkshop.config import CellConfig, load_config

__all__ = ["CellConfig", "load_config"]
```

```python
# tests/chunkshop/__init__.py
```

- [ ] **Step 6: Commit**

```bash
cd /home/yonk/yonk-tools/pg-raggraph
git add benchmarks/age-bakeoff/scripts/chunkshop/__init__.py \
        benchmarks/age-bakeoff/scripts/chunkshop/config.py \
        benchmarks/age-bakeoff/tests/chunkshop/__init__.py \
        benchmarks/age-bakeoff/tests/chunkshop/test_config.py
git commit -m "feat(chunkshop): config model and YAML loader"
```

---

## Task 2: Source adapters

**Files:**
- Create: `scripts/chunkshop/sources/__init__.py`
- Create: `scripts/chunkshop/sources/base.py`
- Create: `scripts/chunkshop/sources/files.py`
- Create: `scripts/chunkshop/sources/json_corpus.py`
- Create: `scripts/chunkshop/sources/pg_table.py`
- Create: `scripts/chunkshop/sources/http.py`
- Create: `scripts/chunkshop/sources/s3.py`
- Test: `tests/chunkshop/test_sources_files.py`, `test_sources_json_corpus.py`

- [ ] **Step 1: Write failing tests for files + json_corpus sources**

```python
# tests/chunkshop/test_sources_files.py
from pathlib import Path
import textwrap
from chunkshop.sources.files import FilesSource as Adapter
from chunkshop.config import FilesSource as Cfg


def test_files_glob_stem_id(tmp_path):
    (tmp_path / "a.md").write_text("alpha")
    (tmp_path / "b.md").write_text("beta")
    adapter = Adapter(Cfg(type="files", glob=str(tmp_path / "*.md"), id_from="stem"))
    docs = sorted(adapter.iter_documents(), key=lambda d: d.id)
    assert [d.id for d in docs] == ["a", "b"]
    assert docs[0].content == "alpha"


def test_files_empty_glob_raises(tmp_path):
    adapter = Adapter(Cfg(type="files", glob=str(tmp_path / "*.md"), id_from="stem"))
    import pytest
    with pytest.raises(ValueError, match="no files"):
        list(adapter.iter_documents())
```

```python
# tests/chunkshop/test_sources_json_corpus.py
import json
from chunkshop.sources.json_corpus import JsonCorpusSource as Adapter
from chunkshop.config import JsonCorpusSource as Cfg


def test_reads_documents_list(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({
        "documents": [
            {"id": "d1", "content": "hello", "title": "H"},
            {"id": "d2", "content": "world", "title": "W"},
        ]
    }))
    adapter = Adapter(Cfg(type="json_corpus", path=str(path)))
    docs = list(adapter.iter_documents())
    assert len(docs) == 2
    assert docs[0].id == "d1"
    assert docs[0].content == "hello"
    assert docs[0].title == "H"
```

- [ ] **Step 2: Run to confirm failures**

Run: `uv run pytest tests/chunkshop/test_sources_files.py tests/chunkshop/test_sources_json_corpus.py -v`
Expected: FAIL (imports missing)

- [ ] **Step 3: Implement base + files + json_corpus**

```python
# scripts/chunkshop/sources/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, Optional, Protocol


@dataclass(frozen=True)
class Document:
    id: str
    content: str
    title: Optional[str] = None
    metadata: Optional[dict] = None


class Source(Protocol):
    def iter_documents(self) -> Iterator[Document]: ...
```

```python
# scripts/chunkshop/sources/files.py
from __future__ import annotations
import glob as _glob
import hashlib
from pathlib import Path
from typing import Iterator

from chunkshop.config import FilesSource as Cfg
from chunkshop.sources.base import Document


class FilesSource:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def iter_documents(self) -> Iterator[Document]:
        paths = sorted(_glob.glob(self.cfg.glob, recursive=True))
        if not paths:
            raise ValueError(f"no files matched glob: {self.cfg.glob}")
        for p in paths:
            path = Path(p)
            text = path.read_text(encoding=self.cfg.encoding, errors="replace")
            doc_id = self._id_for(path)
            yield Document(id=doc_id, content=text, title=path.name, metadata={"source_path": str(path)})

    def _id_for(self, path: Path) -> str:
        mode = self.cfg.id_from
        if mode == "path":
            return str(path)
        if mode == "stem":
            return path.stem
        if mode == "sha1":
            return hashlib.sha1(str(path).encode()).hexdigest()
        raise ValueError(mode)
```

```python
# scripts/chunkshop/sources/json_corpus.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from chunkshop.config import JsonCorpusSource as Cfg
from chunkshop.sources.base import Document


class JsonCorpusSource:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def iter_documents(self) -> Iterator[Document]:
        data = json.loads(Path(self.cfg.path).read_text())
        docs = data[self.cfg.documents_key]
        for row in docs:
            yield Document(
                id=row[self.cfg.id_field],
                content=row[self.cfg.content_field],
                title=row.get(self.cfg.title_field) if self.cfg.title_field else None,
                metadata={k: v for k, v in row.items() if k not in (self.cfg.id_field, self.cfg.content_field, self.cfg.title_field)},
            )
```

```python
# scripts/chunkshop/sources/pg_table.py
from __future__ import annotations
import os
from typing import Iterator

import psycopg
from psycopg import sql

from chunkshop.config import PgTableSource as Cfg
from chunkshop.sources.base import Document


class PgTableSource:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def iter_documents(self) -> Iterator[Document]:
        dsn = os.environ[self.cfg.dsn_env]
        cols = [self.cfg.id_column, self.cfg.content_column]
        if self.cfg.title_column:
            cols.append(self.cfg.title_column)
        ident_cols = [sql.Identifier(c) for c in cols]
        query = sql.SQL("SELECT {cols} FROM {schema}.{table}").format(
            cols=sql.SQL(", ").join(ident_cols),
            schema=sql.Identifier(self.cfg.schema_name),
            table=sql.Identifier(self.cfg.table),
        )
        if self.cfg.where:
            query = query + sql.SQL(" WHERE ") + sql.SQL(self.cfg.where)  # trusted operator input
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(query)
            for row in cur:
                yield Document(
                    id=str(row[0]),
                    content=row[1],
                    title=row[2] if self.cfg.title_column else None,
                )
```

```python
# scripts/chunkshop/sources/http.py
from chunkshop.config import HttpSource as Cfg
from chunkshop.sources.base import Document


class HttpSource:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def iter_documents(self):
        raise NotImplementedError("HTTP source is not yet implemented; submit an issue to request it")
```

```python
# scripts/chunkshop/sources/s3.py
from chunkshop.config import S3Source as Cfg
from chunkshop.sources.base import Document


class S3Source:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def iter_documents(self):
        raise NotImplementedError("S3 source is not yet implemented; submit an issue to request it")
```

```python
# scripts/chunkshop/sources/__init__.py
"""Source registry."""
from chunkshop.config import (
    FilesSource as FilesCfg,
    JsonCorpusSource as JsonCfg,
    PgTableSource as PgCfg,
    HttpSource as HttpCfg,
    S3Source as S3Cfg,
    SourceConfig,
)
from chunkshop.sources.base import Document, Source
from chunkshop.sources.files import FilesSource
from chunkshop.sources.json_corpus import JsonCorpusSource
from chunkshop.sources.pg_table import PgTableSource
from chunkshop.sources.http import HttpSource
from chunkshop.sources.s3 import S3Source


def load_source(cfg: SourceConfig) -> Source:
    if isinstance(cfg, FilesCfg):
        return FilesSource(cfg)
    if isinstance(cfg, JsonCfg):
        return JsonCorpusSource(cfg)
    if isinstance(cfg, PgCfg):
        return PgTableSource(cfg)
    if isinstance(cfg, HttpCfg):
        return HttpSource(cfg)
    if isinstance(cfg, S3Cfg):
        return S3Source(cfg)
    raise ValueError(f"unknown source type: {type(cfg).__name__}")


__all__ = ["Document", "Source", "load_source"]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run pytest tests/chunkshop/test_sources_files.py tests/chunkshop/test_sources_json_corpus.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/sources/ \
        benchmarks/age-bakeoff/tests/chunkshop/test_sources_*.py
git commit -m "feat(chunkshop): source adapters (files, json_corpus, pg_table; http/s3 stubs)"
```

---

## Task 3: Chunker adapters

**Files:**
- Create: `scripts/chunkshop/chunkers/__init__.py`, `base.py`, `sentence_aware.py`, `fixed_overlap.py`, `hierarchy.py`, `neighbor_expand.py`
- Test: `tests/chunkshop/test_chunkers.py`

- [ ] **Step 1: Write failing tests for all 4 chunkers**

```python
# tests/chunkshop/test_chunkers.py
from chunkshop.chunkers import load_chunker
from chunkshop.config import (
    SentenceAwareChunker,
    FixedOverlapChunker,
    HierarchyChunker,
    NeighborExpandChunker,
)
from chunkshop.sources.base import Document


def _doc(content: str, id: str = "d1", title: str | None = None) -> Document:
    return Document(id=id, content=content, title=title)


def test_sentence_aware_uses_age_bakeoff_chunker():
    chunker = load_chunker(SentenceAwareChunker())
    chunks = chunker.chunk(_doc("Hello world.\n\nSecond paragraph here."))
    assert len(chunks) >= 1
    assert all(c.doc_id == "d1" for c in chunks)
    assert chunks[0].seq_num == 0


def test_fixed_overlap_windows():
    words = " ".join([f"w{i}" for i in range(600)])
    chunker = load_chunker(FixedOverlapChunker(type="fixed_overlap", window_words=300, step_words=150))
    chunks = chunker.chunk(_doc(words))
    # 600 words, window=300, step=150 -> starts at 0, 150, 300 -> 3 full windows (last one may be short)
    assert len(chunks) == 3
    # First window: words 0..299 => "w0 w1 ... w299"
    first_words = chunks[0].embedded_content.split()
    assert first_words[0] == "w0" and first_words[-1] == "w299"
    # Second window starts at w150
    second_words = chunks[1].embedded_content.split()
    assert second_words[0] == "w150"


def test_hierarchy_prefixes_heading():
    md = "# Section One\n\nalpha body text\n\n# Section Two\n\nbeta body text"
    chunker = load_chunker(HierarchyChunker(type="hierarchy"))
    chunks = chunker.chunk(_doc(md))
    assert len(chunks) == 2
    # Embedded content has the heading prefixed
    assert chunks[0].embedded_content.startswith("Section One")
    assert "alpha body text" in chunks[0].embedded_content
    # Original content is the body only
    assert "alpha body text" in chunks[0].original_content
    assert not chunks[0].original_content.startswith("Section One")


def test_neighbor_expand_wraps_base():
    chunker = load_chunker(
        NeighborExpandChunker(
            type="neighbor_expand",
            base=FixedOverlapChunker(type="fixed_overlap", window_words=50, step_words=50),
            window=1,
        )
    )
    # 150 words -> base produces 3 non-overlapping chunks; neighbor-expand
    # post-processes so each chunk's embedded_content includes prev+current+next
    words = " ".join([f"w{i}" for i in range(150)])
    chunks = chunker.chunk(_doc(words))
    assert len(chunks) == 3
    # Middle chunk has prev's content, own content, next's content
    middle = chunks[1].embedded_content
    assert "w0" in middle and "w50" in middle and "w100" in middle
    # original_content is just the middle base chunk's content
    assert chunks[1].original_content.split()[0] == "w50"
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/chunkshop/test_chunkers.py -v`
Expected: FAIL (imports missing)

- [ ] **Step 3: Implement base + 4 chunkers**

```python
# scripts/chunkshop/chunkers/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

from chunkshop.sources.base import Document


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    seq_num: int
    original_content: str   # used for fact-matching / audit
    embedded_content: str   # what gets embedded (may differ from original)
    metadata: dict


class Chunker(Protocol):
    def chunk(self, doc: Document) -> list[Chunk]: ...
```

```python
# scripts/chunkshop/chunkers/sentence_aware.py
from __future__ import annotations
from age_bakeoff.chunker import chunk_text as _chunk_text  # baseline chunker used by the bakeoff

from chunkshop.chunkers.base import Chunk
from chunkshop.config import SentenceAwareChunker as Cfg
from chunkshop.sources.base import Document


class SentenceAwareChunker:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def chunk(self, doc: Document) -> list[Chunk]:
        bakeoff_chunks = _chunk_text(text=doc.content, document_id=doc.id, doc_type=self.cfg.doc_type)
        return [
            Chunk(
                doc_id=doc.id,
                seq_num=bc.sequence,
                original_content=bc.content,
                embedded_content=bc.content,
                metadata={"strategy": "sentence_aware"},
            )
            for bc in bakeoff_chunks
        ]
```

```python
# scripts/chunkshop/chunkers/fixed_overlap.py
from __future__ import annotations
from chunkshop.chunkers.base import Chunk
from chunkshop.config import FixedOverlapChunker as Cfg
from chunkshop.sources.base import Document


class FixedOverlapChunker:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        if cfg.step_words <= 0 or cfg.window_words <= 0:
            raise ValueError("window_words and step_words must be positive")

    def chunk(self, doc: Document) -> list[Chunk]:
        words = doc.content.split()
        window = self.cfg.window_words
        step = self.cfg.step_words
        chunks: list[Chunk] = []
        seq = 0
        i = 0
        while i < len(words):
            slice_words = words[i : i + window]
            text = " ".join(slice_words)
            chunks.append(Chunk(
                doc_id=doc.id,
                seq_num=seq,
                original_content=text,
                embedded_content=text,
                metadata={"strategy": "fixed_overlap", "start_word": i, "n_words": len(slice_words)},
            ))
            seq += 1
            if i + window >= len(words):
                break
            i += step
        return chunks
```

```python
# scripts/chunkshop/chunkers/hierarchy.py
from __future__ import annotations
import re

from chunkshop.chunkers.base import Chunk
from chunkshop.config import HierarchyChunker as Cfg
from chunkshop.sources.base import Document

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)$", re.MULTILINE)


class HierarchyChunker:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def chunk(self, doc: Document) -> list[Chunk]:
        text = doc.content
        headings = list(_HEADING.finditer(text))
        if not headings:
            # No headings: whole doc as one chunk, prefix with title if available
            prefix = doc.title or ""
            body = text.strip()
            embedded = f"{prefix}\n\n{body}".strip() if (prefix and self.cfg.prefix_heading) else body
            return [Chunk(
                doc_id=doc.id,
                seq_num=0,
                original_content=body,
                embedded_content=embedded,
                metadata={"strategy": "hierarchy", "heading": prefix},
            )]
        chunks: list[Chunk] = []
        # Prefix before first heading, if substantial
        if headings[0].start() > 0:
            body = text[: headings[0].start()].strip()
            if len(body) >= self.cfg.min_section_chars:
                prefix = doc.title or ""
                embedded = f"{prefix}\n\n{body}".strip() if (prefix and self.cfg.prefix_heading) else body
                chunks.append(Chunk(
                    doc_id=doc.id,
                    seq_num=len(chunks),
                    original_content=body,
                    embedded_content=embedded,
                    metadata={"strategy": "hierarchy", "heading": prefix},
                ))
        for i, m in enumerate(headings):
            heading_text = m.group(2).strip()
            start = m.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            body = text[start:end].strip()
            if len(body) < self.cfg.min_section_chars:
                continue
            embedded = f"{heading_text}\n\n{body}" if self.cfg.prefix_heading else body
            chunks.append(Chunk(
                doc_id=doc.id,
                seq_num=len(chunks),
                original_content=body,
                embedded_content=embedded,
                metadata={"strategy": "hierarchy", "heading": heading_text},
            ))
        return chunks
```

```python
# scripts/chunkshop/chunkers/neighbor_expand.py
from __future__ import annotations

from chunkshop.chunkers.base import Chunk, Chunker
from chunkshop.config import NeighborExpandChunker as Cfg
from chunkshop.sources.base import Document


class NeighborExpandChunker:
    def __init__(self, cfg: Cfg, base: Chunker):
        self.cfg = cfg
        self.base = base

    def chunk(self, doc: Document) -> list[Chunk]:
        base_chunks = self.base.chunk(doc)
        out: list[Chunk] = []
        w = self.cfg.window
        for i, bc in enumerate(base_chunks):
            lo = max(0, i - w)
            hi = min(len(base_chunks) - 1, i + w)
            joined = "\n\n".join(base_chunks[j].embedded_content for j in range(lo, hi + 1))
            out.append(Chunk(
                doc_id=bc.doc_id,
                seq_num=bc.seq_num,
                original_content=bc.original_content,
                embedded_content=joined,
                metadata={**bc.metadata, "neighbor_expand_window": w},
            ))
        return out
```

```python
# scripts/chunkshop/chunkers/__init__.py
"""Chunker registry."""
from chunkshop.chunkers.base import Chunk, Chunker
from chunkshop.chunkers.fixed_overlap import FixedOverlapChunker
from chunkshop.chunkers.hierarchy import HierarchyChunker
from chunkshop.chunkers.neighbor_expand import NeighborExpandChunker
from chunkshop.chunkers.sentence_aware import SentenceAwareChunker
from chunkshop.config import (
    ChunkerConfig,
    FixedOverlapChunker as FixedCfg,
    HierarchyChunker as HierCfg,
    NeighborExpandChunker as NeighborCfg,
    SentenceAwareChunker as SentCfg,
)


def load_chunker(cfg: ChunkerConfig) -> Chunker:
    if isinstance(cfg, SentCfg):
        return SentenceAwareChunker(cfg)
    if isinstance(cfg, FixedCfg):
        return FixedOverlapChunker(cfg)
    if isinstance(cfg, HierCfg):
        return HierarchyChunker(cfg)
    if isinstance(cfg, NeighborCfg):
        base = load_chunker(cfg.base)
        return NeighborExpandChunker(cfg, base)
    raise ValueError(f"unknown chunker type: {type(cfg).__name__}")


__all__ = ["Chunk", "Chunker", "load_chunker"]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run pytest tests/chunkshop/test_chunkers.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/chunkers/ \
        benchmarks/age-bakeoff/tests/chunkshop/test_chunkers.py
git commit -m "feat(chunkshop): 4 chunkers (sentence-aware, fixed-overlap, hierarchy, neighbor-expand)"
```

---

## Task 4: Embedder adapter (fastembed)

**Files:**
- Create: `scripts/chunkshop/embedders/__init__.py`, `base.py`, `fastembed_provider.py`
- Test: `tests/chunkshop/test_embedder_fastembed.py`

- [ ] **Step 1: Write failing test**

```python
# tests/chunkshop/test_embedder_fastembed.py
import numpy as np
from chunkshop.config import FastembedEmbedder
from chunkshop.embedders import load_embedder


def test_bge_small_embeds_to_384_dim():
    cfg = FastembedEmbedder(type="fastembed", model_name="BAAI/bge-small-en-v1.5", dim=384, batch_size=2)
    emb = load_embedder(cfg)
    arr = emb.embed(["hello", "world"])
    assert arr.shape == (2, 384)
    assert arr.dtype == np.float32
    # Normalized vectors have unit norm
    norms = np.linalg.norm(arr, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=0.05)
```

- [ ] **Step 2: Run (expect FAIL; first run also downloads model — may take ~30s)**

Run: `uv run pytest tests/chunkshop/test_embedder_fastembed.py -v -s`
Expected: FAIL (import missing)

- [ ] **Step 3: Implement**

```python
# scripts/chunkshop/embedders/base.py
from __future__ import annotations
from typing import Protocol
import numpy as np


class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...
```

```python
# scripts/chunkshop/embedders/fastembed_provider.py
from __future__ import annotations
import os

import numpy as np
from fastembed import TextEmbedding

from chunkshop.config import FastembedEmbedder as Cfg


class FastembedProvider:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.dim = cfg.dim
        # Some fastembed models need trust_remote_code for nomic; check here
        kwargs = {"model_name": cfg.model_name}
        self._model = TextEmbedding(**kwargs)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        vecs = list(self._model.embed(texts, batch_size=self.cfg.batch_size))
        arr = np.stack(vecs).astype(np.float32)
        if arr.shape[1] != self.dim:
            raise ValueError(
                f"model {self.cfg.model_name} produced dim {arr.shape[1]}, config says {self.dim}"
            )
        return arr
```

```python
# scripts/chunkshop/embedders/__init__.py
from chunkshop.config import EmbedderConfig, FastembedEmbedder as FastCfg
from chunkshop.embedders.base import Embedder
from chunkshop.embedders.fastembed_provider import FastembedProvider


def load_embedder(cfg: EmbedderConfig) -> Embedder:
    if isinstance(cfg, FastCfg):
        return FastembedProvider(cfg)
    raise ValueError(f"unknown embedder type: {type(cfg).__name__}")


__all__ = ["Embedder", "load_embedder"]
```

- [ ] **Step 4: Run tests, confirm pass (will download bge-small on first run)**

Run: `uv run pytest tests/chunkshop/test_embedder_fastembed.py -v -s`
Expected: PASS (1/1). Note: first run downloads ~150 MB.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/embedders/ \
        benchmarks/age-bakeoff/tests/chunkshop/test_embedder_fastembed.py
git commit -m "feat(chunkshop): fastembed embedder provider"
```

---

## Task 5: Extractor adapters

**Files:**
- Create: `scripts/chunkshop/extractors/__init__.py`, `base.py`, `none_provider.py`, `rake_keywords.py`
- Test: `tests/chunkshop/test_extractor_rake.py`
- Modify: `benchmarks/age-bakeoff/pyproject.toml` — add `rake-nltk>=1.0.6` to dev deps

- [ ] **Step 1: Add test dependency to pyproject.toml**

Edit `benchmarks/age-bakeoff/pyproject.toml`, under `dependencies`:
```toml
    "rake-nltk>=1.0.6",
    "nltk>=3.8",
```

Then: `cd benchmarks/age-bakeoff && uv sync`

- [ ] **Step 2: Write failing test**

```python
# tests/chunkshop/test_extractor_rake.py
from chunkshop.config import RakeKeywordsExtractor
from chunkshop.extractors import load_extractor


def test_rake_returns_keywords_sorted():
    extractor = load_extractor(RakeKeywordsExtractor(type="rake_keywords", top_k=3))
    text = "Supreme Court justice Neil Gorsuch wrote the majority opinion in Bostock v. Clayton County. Bostock concerns civil rights and Title VII."
    tags = extractor.extract(text)
    assert isinstance(tags, list)
    assert 1 <= len(tags) <= 3
    # Some legal-domain phrase should appear
    lowered = [t.lower() for t in tags]
    assert any("bostock" in t or "gorsuch" in t or "civil rights" in t or "title vii" in t for t in lowered)


def test_none_returns_empty():
    from chunkshop.config import NoneExtractor
    extractor = load_extractor(NoneExtractor())
    assert extractor.extract("any text") == []
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/chunkshop/test_extractor_rake.py -v`
Expected: FAIL (imports missing)

- [ ] **Step 4: Implement**

```python
# scripts/chunkshop/extractors/base.py
from __future__ import annotations
from typing import Protocol


class Extractor(Protocol):
    def extract(self, text: str) -> list[str]: ...
```

```python
# scripts/chunkshop/extractors/none_provider.py
from chunkshop.config import NoneExtractor as Cfg


class NoneExtractor:
    def __init__(self, cfg: Cfg | None = None):
        self.cfg = cfg

    def extract(self, text: str) -> list[str]:
        return []
```

```python
# scripts/chunkshop/extractors/rake_keywords.py
from __future__ import annotations

from chunkshop.config import RakeKeywordsExtractor as Cfg


class RakeKeywordsExtractor:
    def __init__(self, cfg: Cfg):
        # Lazy import — nltk stopwords are downloaded on first call
        import nltk
        try:
            nltk.data.find("corpora/stopwords")
        except LookupError:
            nltk.download("stopwords", quiet=True)
        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            nltk.download("punkt", quiet=True)
        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)
        from rake_nltk import Rake
        self._rake_cls = Rake
        self.cfg = cfg

    def extract(self, text: str) -> list[str]:
        r = self._rake_cls(min_length=1)
        r.extract_keywords_from_text(text)
        ranked = r.get_ranked_phrases()
        return [p for p in ranked if len(p) >= self.cfg.min_chars][: self.cfg.top_k]
```

```python
# scripts/chunkshop/extractors/__init__.py
from chunkshop.config import (
    ExtractorConfig,
    NoneExtractor as NoneCfg,
    RakeKeywordsExtractor as RakeCfg,
)
from chunkshop.extractors.base import Extractor
from chunkshop.extractors.none_provider import NoneExtractor
from chunkshop.extractors.rake_keywords import RakeKeywordsExtractor


def load_extractor(cfg: ExtractorConfig) -> Extractor:
    if isinstance(cfg, NoneCfg):
        return NoneExtractor(cfg)
    if isinstance(cfg, RakeCfg):
        return RakeKeywordsExtractor(cfg)
    raise ValueError(f"unknown extractor type: {type(cfg).__name__}")


__all__ = ["Extractor", "load_extractor"]
```

- [ ] **Step 5: Run tests, confirm pass (downloads nltk stopwords on first run)**

Run: `uv run pytest tests/chunkshop/test_extractor_rake.py -v`
Expected: PASS (2/2)

- [ ] **Step 6: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/extractors/ \
        benchmarks/age-bakeoff/tests/chunkshop/test_extractor_rake.py \
        benchmarks/age-bakeoff/pyproject.toml \
        benchmarks/age-bakeoff/uv.lock
git commit -m "feat(chunkshop): extractor adapters (none, rake_keywords) + rake-nltk dep"
```

---

## Task 6: PgVector sink

**Files:**
- Create: `scripts/chunkshop/sink.py`
- Test: `tests/chunkshop/test_sink.py` (requires PG at `localhost:5434`)

- [ ] **Step 1: Write integration test**

```python
# tests/chunkshop/test_sink.py
import os
import pytest
import psycopg
import numpy as np
from chunkshop.chunkers.base import Chunk
from chunkshop.config import TargetConfig
from chunkshop.sink import PgVectorSink


DSN_ENV = "AGE_BAKEOFF_PGRG_DSN"
DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"


def _require_pg():
    dsn = os.environ.get(DSN_ENV, DEFAULT_DSN)
    try:
        with psycopg.connect(dsn, connect_timeout=2) as _:
            pass
    except Exception:
        pytest.skip(f"PG at {dsn} not reachable")
    os.environ[DSN_ENV] = dsn
    return dsn


def test_create_and_write_roundtrip():
    dsn = _require_pg()
    cfg = TargetConfig(
        dsn_env=DSN_ENV,
        **{"schema": "factorial_test"},
        table="sink_smoke",
        overwrite=True,
        hnsw=False,  # skip index on tiny test
    )
    sink = PgVectorSink(cfg, embed_dim=4)
    sink.create_table()
    chunks = [
        Chunk(doc_id="d1", seq_num=0, original_content="hello",
              embedded_content="hello", metadata={"strategy": "t"}),
        Chunk(doc_id="d1", seq_num=1, original_content="world",
              embedded_content="world", metadata={"strategy": "t"}),
    ]
    embeddings = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    tags = [["hi"], ["world", "planet"]]
    sink.write_document("d1", chunks, embeddings, tags)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, doc_id, seq_num, original_content, tags FROM factorial_test.sink_smoke ORDER BY seq_num")
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("d1::0", "d1", 0, "hello", ["hi"])
        assert rows[1] == ("d1::1", "d1", 1, "world", ["world", "planet"])
        cur.execute("DROP SCHEMA factorial_test CASCADE")
        conn.commit()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/chunkshop/test_sink.py -v -s`
Expected: FAIL (import missing). If PG isn't up: `docker compose up -d` first from the bakeoff dir.

- [ ] **Step 3: Implement**

```python
# scripts/chunkshop/sink.py
"""pgvector sink: creates target table, upserts chunk rows per-document."""
from __future__ import annotations
import json
import os
from typing import Iterable

import numpy as np
import psycopg
from psycopg import sql

from chunkshop.chunkers.base import Chunk
from chunkshop.config import TargetConfig


class PgVectorSink:
    def __init__(self, cfg: TargetConfig, embed_dim: int):
        self.cfg = cfg
        self.embed_dim = embed_dim
        self._dsn = os.environ[cfg.dsn_env]

    def _ident(self, *parts: str) -> sql.Composed:
        return sql.SQL(".").join(sql.Identifier(p) for p in parts)

    def create_table(self) -> None:
        fq = self._ident(self.cfg.schema_name, self.cfg.table)
        create_ext = sql.SQL("CREATE EXTENSION IF NOT EXISTS vector")
        create_schema = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.cfg.schema_name))
        drop_if = sql.SQL("DROP TABLE IF EXISTS {}").format(fq)
        create_tbl = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {tbl} (
                id text PRIMARY KEY,
                doc_id text NOT NULL,
                seq_num int NOT NULL,
                original_content text NOT NULL,
                embedded_content text NOT NULL,
                tags text[] NOT NULL DEFAULT '{{}}',
                metadata jsonb NOT NULL DEFAULT '{{}}',
                embedding vector({dim}) NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
        """).format(tbl=fq, dim=sql.Literal(self.embed_dim))
        create_doc_idx = sql.SQL(
            "CREATE INDEX IF NOT EXISTS {name} ON {tbl} (doc_id, seq_num)"
        ).format(name=sql.Identifier(f"{self.cfg.table}_doc_seq_idx"), tbl=fq)
        create_hnsw = sql.SQL(
            "CREATE INDEX IF NOT EXISTS {name} ON {tbl} USING hnsw (embedding vector_cosine_ops)"
        ).format(name=sql.Identifier(f"{self.cfg.table}_emb_hnsw_idx"), tbl=fq)

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(create_ext)
            cur.execute(create_schema)
            if self.cfg.overwrite:
                cur.execute(drop_if)
            cur.execute(create_tbl)
            cur.execute(create_doc_idx)
            if self.cfg.hnsw:
                cur.execute(create_hnsw)
            conn.commit()

    def write_document(
        self, doc_id: str, chunks: list[Chunk], embeddings: np.ndarray, tags_per_chunk: list[list[str]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch")
        if len(chunks) != len(tags_per_chunk):
            raise ValueError(f"chunks ({len(chunks)}) and tags ({len(tags_per_chunk)}) length mismatch")
        fq = self._ident(self.cfg.schema_name, self.cfg.table)
        rows = []
        for c, emb, tags in zip(chunks, embeddings, tags_per_chunk):
            vec_literal = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
            rows.append((
                f"{c.doc_id}::{c.seq_num}",
                c.doc_id,
                c.seq_num,
                c.original_content,
                c.embedded_content,
                tags,
                json.dumps(c.metadata),
                vec_literal,
            ))
        stmt = sql.SQL("""
            INSERT INTO {tbl} (id, doc_id, seq_num, original_content, embedded_content, tags, metadata, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
            ON CONFLICT (id) DO UPDATE SET
                original_content = EXCLUDED.original_content,
                embedded_content = EXCLUDED.embedded_content,
                tags = EXCLUDED.tags,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
        """).format(tbl=fq)
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.executemany(stmt, rows)
            conn.commit()

    def count_docs(self) -> int:
        fq = self._ident(self.cfg.schema_name, self.cfg.table)
        stmt = sql.SQL("SELECT COUNT(DISTINCT doc_id) FROM {}").format(fq)
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(stmt)
            return cur.fetchone()[0]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `docker compose up -d && uv run pytest tests/chunkshop/test_sink.py -v -s`
Expected: PASS (1/1)

- [ ] **Step 5: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/sink.py \
        benchmarks/age-bakeoff/tests/chunkshop/test_sink.py
git commit -m "feat(chunkshop): pgvector sink with per-doc upsert"
```

---

## Task 7: Single-cell runner + CLI `ingest` subcommand

**Files:**
- Create: `scripts/chunkshop/runner.py`
- Create: `scripts/chunkshop/cli.py`
- Test: `tests/chunkshop/test_runner.py`
- Modify: `pyproject.toml` to add `[project.scripts]` entry `chunkshop = "chunkshop.cli:cli"` (optional but convenient)

- [ ] **Step 1: Write failing test for runner**

```python
# tests/chunkshop/test_runner.py
import os
import json
import textwrap
import pytest
import psycopg
from chunkshop.config import load_config
from chunkshop.runner import run_cell


DSN = os.environ.get("AGE_BAKEOFF_PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg")


def _require_pg():
    try:
        with psycopg.connect(DSN, connect_timeout=2):
            pass
    except Exception:
        pytest.skip(f"PG at {DSN} not reachable")
    os.environ["AGE_BAKEOFF_PGRG_DSN"] = DSN


def test_run_cell_end_to_end(tmp_path):
    _require_pg()
    corpus = tmp_path / "c.json"
    corpus.write_text(json.dumps({
        "documents": [
            {"id": "d1", "content": "The Supreme Court decided Bostock.", "title": "Case A"},
            {"id": "d2", "content": "Apple v. Pepper is an antitrust case.", "title": "Case B"},
        ]
    }))
    yaml_text = textwrap.dedent(f"""
        cell_name: runner_smoke
        source:
          type: json_corpus
          path: {corpus}
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: BAAI/bge-small-en-v1.5
          dim: 384
        target:
          dsn_env: AGE_BAKEOFF_PGRG_DSN
          schema: factorial_test
          table: runner_smoke
          overwrite: true
          hnsw: false
        runtime:
          doc_limit: 2
    """)
    cfg_path = tmp_path / "cell.yaml"
    cfg_path.write_text(yaml_text)
    cfg = load_config(cfg_path)

    result = run_cell(cfg)
    assert result.docs_processed == 2
    assert result.chunks_written >= 2
    assert result.error is None

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM factorial_test.runner_smoke")
        assert cur.fetchone()[0] >= 2
        cur.execute("DROP SCHEMA factorial_test CASCADE")
        conn.commit()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/chunkshop/test_runner.py -v -s`
Expected: FAIL (imports missing)

- [ ] **Step 3: Implement `runner.py`**

```python
# scripts/chunkshop/runner.py
"""Single-cell runner: wires source -> chunker -> embedder -> extractor -> sink."""
from __future__ import annotations
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chunkshop.chunkers import load_chunker
from chunkshop.config import CellConfig
from chunkshop.embedders import load_embedder
from chunkshop.extractors import load_extractor
from chunkshop.sink import PgVectorSink
from chunkshop.sources import load_source


@dataclass
class CellResult:
    cell_name: str
    docs_processed: int
    chunks_written: int
    wall_seconds: float
    error: Optional[str] = None


def _log(msg: str, log_path: Optional[Path]) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if log_path:
        with log_path.open("a") as f:
            f.write(line + "\n")


def run_cell(cfg: CellConfig) -> CellResult:
    # Pin CPU before any embedding work (must be set before fastembed imports ONNX)
    os.environ["OMP_NUM_THREADS"] = str(cfg.runtime.omp_num_threads)
    os.environ["MKL_NUM_THREADS"] = str(cfg.runtime.omp_num_threads)

    log_path = Path(cfg.runtime.log_path) if cfg.runtime.log_path else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    _log(f"cell {cfg.cell_name} starting", log_path)
    _log(f"config: {cfg.model_dump_json(by_alias=True)}", log_path)
    try:
        source = load_source(cfg.source)
        chunker = load_chunker(cfg.chunker)
        embedder = load_embedder(cfg.embedder)
        extractor = load_extractor(cfg.extractor)
        sink = PgVectorSink(cfg.target, embed_dim=cfg.embedder.dim)

        _log("creating target table", log_path)
        sink.create_table()

        docs_processed = 0
        chunks_written = 0
        limit = cfg.runtime.doc_limit
        heartbeat = cfg.runtime.heartbeat_every

        for doc in source.iter_documents():
            if limit is not None and docs_processed >= limit:
                break
            chunks = chunker.chunk(doc)
            if not chunks:
                docs_processed += 1
                continue
            texts = [c.embedded_content for c in chunks]
            embeddings = embedder.embed(texts)
            tags = [extractor.extract(c.original_content) for c in chunks]
            sink.write_document(doc.id, chunks, embeddings, tags)
            chunks_written += len(chunks)
            docs_processed += 1
            if docs_processed % heartbeat == 0:
                elapsed = time.time() - start
                _log(
                    f"heartbeat docs={docs_processed} chunks={chunks_written} elapsed={elapsed:.1f}s",
                    log_path,
                )

        wall = time.time() - start
        _log(
            f"cell {cfg.cell_name} DONE docs={docs_processed} chunks={chunks_written} wall={wall:.1f}s",
            log_path,
        )
        return CellResult(
            cell_name=cfg.cell_name,
            docs_processed=docs_processed,
            chunks_written=chunks_written,
            wall_seconds=wall,
            error=None,
        )
    except Exception as exc:
        wall = time.time() - start
        import traceback
        tb = traceback.format_exc()
        _log(f"cell {cfg.cell_name} FAILED: {exc}\n{tb}", log_path)
        return CellResult(
            cell_name=cfg.cell_name,
            docs_processed=0,
            chunks_written=0,
            wall_seconds=wall,
            error=str(exc),
        )
```

- [ ] **Step 4: Implement `cli.py` with `ingest` subcommand**

```python
# scripts/chunkshop/cli.py
"""chunkshop CLI — ingest, orchestrate, init-schema."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import click

from chunkshop.config import load_config
from chunkshop.runner import run_cell


@click.group()
@click.version_option(version="0.1.0", prog_name="chunkshop")
def cli():
    """Reusable ingestion tool: source -> chunker -> embedder -> extractor -> pgvector table.

    Run one cell with `chunkshop ingest --config cell.yaml`.
    Run N cells in parallel with `chunkshop orchestrate --config-dir configs/`.
    """


@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to the YAML/JSON cell config.")
@click.option("--doc-limit", type=int, default=None,
              help="Override runtime.doc_limit in the YAML (useful for smoke tests).")
@click.option("--log", "log_path", type=click.Path(path_type=Path), default=None,
              help="Override runtime.log_path in the YAML.")
@click.option("--omp-threads", type=int, default=None,
              help="Override OMP_NUM_THREADS. Default from YAML (usually 1).")
def ingest(config: Path, doc_limit, log_path, omp_threads):
    """Run one cell end-to-end: read source -> chunk -> embed -> extract tags -> write to pgvector table."""
    cfg = load_config(config)
    if doc_limit is not None:
        cfg.runtime.doc_limit = doc_limit
    if log_path is not None:
        cfg.runtime.log_path = str(log_path)
    if omp_threads is not None:
        cfg.runtime.omp_num_threads = omp_threads
    result = run_cell(cfg)
    click.echo(json.dumps({
        "cell_name": result.cell_name,
        "docs_processed": result.docs_processed,
        "chunks_written": result.chunks_written,
        "wall_seconds": round(result.wall_seconds, 2),
        "error": result.error,
    }, indent=2))
    sys.exit(1 if result.error else 0)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/chunkshop/test_runner.py -v -s`
Expected: PASS (1/1)

Also verify CLI works:
```
uv run python -m chunkshop.cli ingest --help
```
Expected: click help text printed.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/runner.py \
        benchmarks/age-bakeoff/scripts/chunkshop/cli.py \
        benchmarks/age-bakeoff/tests/chunkshop/test_runner.py
git commit -m "feat(chunkshop): single-cell runner + ingest CLI"
```

---

## Task 8: Orchestrator + CLI `orchestrate` subcommand

**Files:**
- Create: `scripts/chunkshop/orchestrator.py`
- Modify: `scripts/chunkshop/cli.py` (add `orchestrate` subcommand)
- Test: `tests/chunkshop/test_orchestrator.py`

- [ ] **Step 1: Write failing test (uses 2 tiny YAMLs against real PG)**

```python
# tests/chunkshop/test_orchestrator.py
import json
import os
import textwrap
import pytest
import psycopg
from pathlib import Path

from chunkshop.orchestrator import orchestrate, OrchestrationResult


DSN = os.environ.get("AGE_BAKEOFF_PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg")


def _require_pg():
    try:
        with psycopg.connect(DSN, connect_timeout=2):
            pass
    except Exception:
        pytest.skip(f"PG at {DSN} not reachable")
    os.environ["AGE_BAKEOFF_PGRG_DSN"] = DSN


def _mini_yaml(tmp_path: Path, name: str, corpus: Path) -> Path:
    y = tmp_path / f"{name}.yaml"
    y.write_text(textwrap.dedent(f"""
        cell_name: {name}
        source:
          type: json_corpus
          path: {corpus}
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: BAAI/bge-small-en-v1.5
          dim: 384
        target:
          dsn_env: AGE_BAKEOFF_PGRG_DSN
          schema: factorial_test
          table: {name}
          overwrite: true
          hnsw: false
        runtime:
          doc_limit: 1
          log_path: {tmp_path / f"{name}.log"}
    """))
    return y


def test_orchestrate_two_cells_smoke(tmp_path):
    _require_pg()
    corpus = tmp_path / "c.json"
    corpus.write_text(json.dumps({"documents": [{"id": "d1", "content": "x y z", "title": ""}]}))
    y1 = _mini_yaml(tmp_path, "cell_one", corpus)
    y2 = _mini_yaml(tmp_path, "cell_two", corpus)

    result: OrchestrationResult = orchestrate(
        configs=[y1, y2],
        concurrency=2,
        checkpoint_seconds=[2, 5],
    )
    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA factorial_test CASCADE")
        conn.commit()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/chunkshop/test_orchestrator.py -v -s`
Expected: FAIL (imports missing)

- [ ] **Step 3: Implement orchestrator (uses `subprocess.Popen` so each worker is a separate Python process — avoids fastembed's ONNX global state conflicts)**

```python
# scripts/chunkshop/orchestrator.py
"""Parallel orchestration: spawn N cells as subprocesses with checkpoint polling."""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CellHandle:
    config_path: Path
    proc: subprocess.Popen
    log_path: Optional[Path]
    started_at: float
    done_at: Optional[float] = None
    returncode: Optional[int] = None


@dataclass
class OrchestrationResult:
    total: int
    succeeded: int
    failed: int
    cells: list[dict] = field(default_factory=list)


def _spawn_cell(config_path: Path, extra_env: Optional[dict] = None) -> CellHandle:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    # Each worker is a subprocess running `python -m chunkshop.cli ingest --config X`
    cmd = [sys.executable, "-m", "chunkshop.cli", "ingest", "--config", str(config_path)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,  # so we can kill the whole group on timeout
    )
    return CellHandle(config_path=config_path, proc=proc, log_path=None, started_at=time.time())


def orchestrate(
    configs: list[Path],
    concurrency: int = 4,
    checkpoint_seconds: Optional[list[int]] = None,
    overall_timeout_seconds: int = 2 * 60 * 60,  # 2h default
) -> OrchestrationResult:
    checkpoints = sorted(checkpoint_seconds or [60, 120, 300, 600])
    pending = list(configs)
    running: list[CellHandle] = []
    done: list[CellHandle] = []
    started = time.time()
    next_checkpoint_idx = 0

    while pending or running:
        # Fill pool
        while pending and len(running) < concurrency:
            cp = pending.pop(0)
            h = _spawn_cell(cp)
            running.append(h)
            print(f"[orchestrator] started {cp.name} pid={h.proc.pid}", flush=True)

        # Poll for completions
        still_running: list[CellHandle] = []
        for h in running:
            rc = h.proc.poll()
            if rc is None:
                still_running.append(h)
            else:
                h.returncode = rc
                h.done_at = time.time()
                status = "OK" if rc == 0 else f"FAIL(rc={rc})"
                wall = h.done_at - h.started_at
                print(f"[orchestrator] finished {h.config_path.name} {status} wall={wall:.1f}s", flush=True)
                done.append(h)
        running = still_running

        # Checkpoint report
        elapsed = time.time() - started
        if next_checkpoint_idx < len(checkpoints) and elapsed >= checkpoints[next_checkpoint_idx]:
            _checkpoint_report(running, done, elapsed)
            next_checkpoint_idx += 1

        # Overall timeout
        if elapsed > overall_timeout_seconds:
            print(f"[orchestrator] OVERALL TIMEOUT at {elapsed:.0f}s, killing {len(running)} workers", flush=True)
            for h in running:
                try:
                    os.killpg(os.getpgid(h.proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                h.returncode = -1
                h.done_at = time.time()
                done.append(h)
            break

        time.sleep(1.0)

    succeeded = sum(1 for h in done if h.returncode == 0)
    failed = len(done) - succeeded
    cell_rows = [
        {
            "config": str(h.config_path),
            "rc": h.returncode,
            "wall_seconds": round((h.done_at or time.time()) - h.started_at, 2),
        }
        for h in done
    ]
    return OrchestrationResult(total=len(configs), succeeded=succeeded, failed=failed, cells=cell_rows)


def _checkpoint_report(running: list[CellHandle], done: list[CellHandle], elapsed: float) -> None:
    rows = []
    for h in running:
        rows.append(f"  RUN  {h.config_path.name}  t={time.time() - h.started_at:.0f}s")
    for h in done:
        status = "OK" if h.returncode == 0 else f"FAIL({h.returncode})"
        rows.append(f"  DONE {h.config_path.name}  {status}")
    body = "\n".join(rows)
    print(f"[orchestrator] checkpoint t={elapsed:.0f}s ({len(running)} running, {len(done)} done)\n{body}", flush=True)
```

- [ ] **Step 4: Add `orchestrate` subcommand to `cli.py`**

Append to `scripts/chunkshop/cli.py`:

```python
@cli.command()
@click.option("--config-dir", "-d", type=click.Path(exists=True, path_type=Path), default=None,
              help="Directory of YAML configs; every *.yaml/*.yml runs as one cell.")
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path), multiple=True,
              help="Explicit YAML paths (repeatable). Mutually exclusive with --config-dir.")
@click.option("--concurrency", type=int, default=4, show_default=True,
              help="Max parallel cells.")
@click.option("--checkpoints", default="60,120,300,600", show_default=True,
              help="Comma-separated seconds at which to emit a status report.")
@click.option("--timeout", type=int, default=2 * 60 * 60, show_default=True,
              help="Overall timeout in seconds before killing surviving workers.")
@click.option("--smoke/--full", default=False,
              help="Smoke mode: force --doc-limit=1, sequential (concurrency=1).")
def orchestrate(config_dir, config, concurrency, checkpoints, timeout, smoke):
    """Run N cells in parallel, emit checkpoint reports at t=60/120/300/600s by default."""
    from chunkshop.orchestrator import orchestrate as _orch

    if config_dir and config:
        raise click.UsageError("--config-dir and --config are mutually exclusive")
    if not config_dir and not config:
        raise click.UsageError("provide --config-dir or one or more --config")

    if config_dir:
        paths = sorted(
            [p for p in config_dir.glob("*.yaml")] + [p for p in config_dir.glob("*.yml")]
        )
    else:
        paths = list(config)

    if not paths:
        raise click.UsageError(f"no YAML configs found")

    if smoke:
        concurrency = 1
        # Rewrite each YAML in a tmp copy with doc_limit=1
        import tempfile
        import yaml as _yaml
        tmp = Path(tempfile.mkdtemp(prefix="chunkshop-smoke-"))
        new_paths = []
        for p in paths:
            data = _yaml.safe_load(p.read_text())
            data.setdefault("runtime", {})["doc_limit"] = 1
            out = tmp / p.name
            out.write_text(_yaml.safe_dump(data, sort_keys=False))
            new_paths.append(out)
        paths = new_paths

    cp_list = [int(x) for x in checkpoints.split(",") if x.strip()]
    result = _orch(configs=paths, concurrency=concurrency, checkpoint_seconds=cp_list, overall_timeout_seconds=timeout)
    click.echo(json.dumps({
        "total": result.total,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "cells": result.cells,
    }, indent=2))
    sys.exit(1 if result.failed else 0)
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `uv run pytest tests/chunkshop/test_orchestrator.py -v -s`
Expected: PASS (1/1)

Sanity-check CLI:
```
uv run python -m chunkshop.cli orchestrate --help
```

- [ ] **Step 6: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/orchestrator.py \
        benchmarks/age-bakeoff/scripts/chunkshop/cli.py \
        benchmarks/age-bakeoff/tests/chunkshop/test_orchestrator.py
git commit -m "feat(chunkshop): parallel orchestrator with checkpoint polling + smoke mode"
```

---

## Task 9: 12 factorial YAML configs + README

**Files:**
- Create: `scripts/chunkshop/configs/example-files-to-bge.yaml`
- Create: `scripts/chunkshop/configs/factorial/{A,B,C,D}-{bge-small,bge-base,nomic}.yaml` (12 files)
- Create: `scripts/chunkshop/README.md`

- [ ] **Step 1: Author the 12 factorial YAMLs**

Template — `configs/factorial/A-bge-small.yaml`:
```yaml
cell_name: factorial_a_bge_small
source:
  type: json_corpus
  path: /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff/src/age_bakeoff/extraction/data/scotus.json
chunker:
  type: sentence_aware
embedder:
  type: fastembed
  model_name: BAAI/bge-small-en-v1.5
  dim: 384
target:
  dsn_env: AGE_BAKEOFF_PGRG_DSN
  schema: factorial
  table: a_bge_small
  overwrite: true
  hnsw: true
runtime:
  omp_num_threads: 1
  log_path: /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff/logs/factorial/a_bge_small.log
```

Variants:
- **Chunker A** → `{type: sentence_aware}`
- **Chunker B** → `{type: fixed_overlap, window_words: 300, step_words: 150}`
- **Chunker C** → `{type: hierarchy}`
- **Chunker D** → `{type: neighbor_expand, window: 1, base: {type: sentence_aware}}`
- **Embedder bge-small** → `{type: fastembed, model_name: BAAI/bge-small-en-v1.5, dim: 384}`
- **Embedder bge-base** → `{type: fastembed, model_name: BAAI/bge-base-en-v1.5, dim: 768}`
- **Embedder nomic** → `{type: fastembed, model_name: nomic-ai/nomic-embed-text-v1.5, dim: 768}`

Table names: `a_bge_small`, `a_bge_base`, `a_nomic`, `b_bge_small`, …, `d_nomic`.
Log files: `logs/factorial/{table}.log`.

Generate all 12 in one sitting — each is ~20 lines of YAML, same pattern.

- [ ] **Step 2: Author `example-files-to-bge.yaml`** — a documented reference for end users:

```yaml
# Example: ingest markdown files from disk into a pgvector table with bge-small embeddings.
# Usage:
#   export AGE_BAKEOFF_PGRG_DSN="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"
#   chunkshop ingest --config example-files-to-bge.yaml
cell_name: example_files
source:
  type: files
  glob: /path/to/your/docs/**/*.md
  id_from: stem                    # stem | path | sha1
  encoding: utf-8
chunker:
  type: sentence_aware             # other options: fixed_overlap | hierarchy | neighbor_expand
embedder:
  type: fastembed
  model_name: BAAI/bge-small-en-v1.5
  dim: 384
  batch_size: 64
extractor:
  type: none                       # or: rake_keywords (local, no LLM)
target:
  dsn_env: AGE_BAKEOFF_PGRG_DSN
  schema: chunkshop                 # any schema; will be created if missing
  table: my_docs
  overwrite: false                 # set to true to drop+recreate
  hnsw: true                        # set to false for small test tables
runtime:
  omp_num_threads: 1
  heartbeat_every: 25              # log every N docs
  doc_limit: null                  # set to an int for smoke tests
  log_path: /tmp/chunkshop-example.log
```

- [ ] **Step 3: Author `README.md`**

```markdown
# chunkshop

Reusable ingestion tool. Pulls text from a source, chunks it, embeds it, optionally
tags it with keywords, and lands the result in a pgvector table. One YAML file =
one end-to-end "cell".

## Quickstart

    export AGE_BAKEOFF_PGRG_DSN="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"
    chunkshop ingest --config configs/example-files-to-bge.yaml

Or run many YAMLs in parallel (4 at a time, checkpointing at 60/120/300/600s):

    chunkshop orchestrate --config-dir configs/factorial --concurrency 4

Smoke test all configs with 1 doc each:

    chunkshop orchestrate --config-dir configs/factorial --smoke

## Config shape

See `configs/example-files-to-bge.yaml`. Every cell has five sections:

| Section   | Types available                                                              |
|-----------|------------------------------------------------------------------------------|
| source    | files · json_corpus · pg_table · http (stub) · s3 (stub)                     |
| chunker   | sentence_aware · fixed_overlap · hierarchy · neighbor_expand                 |
| embedder  | fastembed (any HuggingFace model fastembed supports)                         |
| extractor | none · rake_keywords                                                         |
| target    | pgvector table `{schema}.{table}` with HNSW index                            |

## Table schema

    CREATE TABLE {schema}.{table} (
        id                  text PRIMARY KEY,        -- "{doc_id}::{seq_num}"
        doc_id              text NOT NULL,
        seq_num             int  NOT NULL,
        original_content    text NOT NULL,           -- raw chunk, used for grep/fact-match
        embedded_content    text NOT NULL,           -- what was embedded (may include heading prefix, neighbor text, etc.)
        tags                text[] NOT NULL DEFAULT '{}',
        metadata            jsonb NOT NULL DEFAULT '{}',
        embedding           vector({dim}) NOT NULL,
        created_at          timestamptz NOT NULL DEFAULT now()
    );

## Factorial experiment

`configs/factorial/*.yaml` — 12 cells (4 chunkers × 3 embedders) for the scotus
retrieval-coverage experiment. See
`docs/superpowers/plans/2026-04-19-chunkshop-ingestion-tool.md`.
```

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/scripts/chunkshop/configs/ \
        benchmarks/age-bakeoff/scripts/chunkshop/README.md
git commit -m "feat(chunkshop): 12 factorial YAMLs + example config + README"
```

---

## Task 10: Smoke run — 1 doc through all 12 cells

**Files:**
- None new; just execute.

- [ ] **Step 1: Ensure PG is up and `AGE_BAKEOFF_PGRG_DSN` is set**

```bash
cd /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff
docker compose up -d
export AGE_BAKEOFF_PGRG_DSN="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"
```

- [ ] **Step 2: Run smoke mode**

```bash
uv run python -m chunkshop.cli orchestrate \
  --config-dir scripts/chunkshop/configs/factorial \
  --smoke 2>&1 | tee /tmp/chunkshop-smoke.log
```

Expected: all 12 cells exit 0, total wall time a few minutes (one doc per cell). Any non-zero rc = fix it before Task 11.

- [ ] **Step 3: Verify each table has ≥1 row**

```bash
psql "$AGE_BAKEOFF_PGRG_DSN" -c "
  SELECT table_name, (xpath('/row/c/text()', query_to_xml('SELECT COUNT(*) c FROM factorial.' || quote_ident(table_name), false, false, '')))[1]::text::int AS rowcount
  FROM information_schema.tables
  WHERE table_schema = 'factorial'
  ORDER BY table_name;
"
```

Expected: 12 tables, each with ≥1 row.

- [ ] **Step 4: Fix any failures** — if a cell failed, read its `/home/yonk/.../logs/factorial/{cell}.log`, diagnose, fix, re-run just that cell.

---

## Task 11: Full run — 772 docs × 12 cells, 4 at a time

**Files:**
- None new; just execute.

- [ ] **Step 1: Truncate / overwrite existing smoke rows** (overwrite: true in YAMLs handles this)

- [ ] **Step 2: Launch in background, monitor**

```bash
cd /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff
mkdir -p logs/factorial
nohup uv run python -m chunkshop.cli orchestrate \
  --config-dir scripts/chunkshop/configs/factorial \
  --concurrency 4 \
  --checkpoints 60,120,300,600,1200,1800,3600 \
  --timeout 14400 \
  > /tmp/chunkshop-full.log 2>&1 &

echo "orchestrator PID: $!"
```

Poll progress (from a different terminal / Bash call):

```bash
tail -f /tmp/chunkshop-full.log
# or
ls -lh logs/factorial/*.log
psql "$AGE_BAKEOFF_PGRG_DSN" -c "
  SELECT
    table_name,
    (xpath('/row/c/text()', query_to_xml('SELECT COUNT(DISTINCT doc_id) c FROM factorial.' || quote_ident(table_name), false, false, '')))[1]::text::int AS docs,
    (xpath('/row/c/text()', query_to_xml('SELECT COUNT(*) c FROM factorial.' || quote_ident(table_name), false, false, '')))[1]::text::int AS rows
  FROM information_schema.tables
  WHERE table_schema = 'factorial'
  ORDER BY docs DESC;
"
```

- [ ] **Step 3: Confirm all 12 cells completed**

Final `chunkshop-full.log` should end with a JSON block showing `"succeeded": 12, "failed": 0`.

- [ ] **Step 4: Commit the run evidence**

```bash
# logs/factorial/*.log is useful for root-cause diagnostics
git add benchmarks/age-bakeoff/logs/factorial/ 2>/dev/null || true
git add /tmp/chunkshop-full.log || true  # skip if gitignored
git commit -m "chore(chunkshop): factorial full-run logs (12 cells, scotus corpus)"
```

(Skip this commit if the run logs are gitignored. What matters is the 12 populated tables in PG.)

---

## Task 12: Probe-query tool + report

**Files:**
- Create: `scripts/factorial-probe-query.py`
- Create: `benchmarks/age-bakeoff/results/diagnostics/factorial-probe.json` (output)
- Create: `benchmarks/age-bakeoff/results/diagnostics/factorial-probe-REPORT.md` (output)
- Delete: `scripts/factorial-probe.py` and `tests/test_factorial_probe.py` (superseded)

- [ ] **Step 1: Delete the superseded in-memory script + tests**

```bash
git rm benchmarks/age-bakeoff/scripts/factorial-probe.py \
       benchmarks/age-bakeoff/tests/test_factorial_probe.py
```

- [ ] **Step 2: Implement `factorial-probe-query.py`**

```python
#!/usr/bin/env python
"""Probe the 12 factorial.* tables with 4 scotus probes and produce the report.

Reads:
  - factorial.{a,b,c,d}_{bge_small,bge_base,nomic} tables (chunk_id, original_content, embedded_content, embedding)
  - benchmarks/age-bakeoff/questions/scotus.yaml (required_facts per probe)

For each (cell, probe):
  1. Embed the probe question with the cell's embedder model.
  2. SELECT ... ORDER BY embedding <=> $1 LIMIT 50 FROM factorial.{table}.
  3. Compute rank_of_first_gold_chunk, top10_hit, top50_hit, per_fact_recall_at_10,
     required_facts_matched, required_facts_missed, using case-insensitive substring
     match of required_facts against original_content.

Writes:
  - results/diagnostics/factorial-probe.json
  - results/diagnostics/factorial-probe-REPORT.md (with TL;DR + 12-row ranked table + decision line)
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import yaml
from fastembed import TextEmbedding

PROBES = ["scotus-q-018", "scotus-q-004", "scotus-q-008", "scotus-q-025"]
FAILING_PROBES = ["scotus-q-004", "scotus-q-008", "scotus-q-025"]

CELLS = [
    # (chunking, embedding, table, model_name, dim)
    ("A", "bge-small", "a_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("A", "bge-base",  "a_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("A", "nomic",     "a_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("B", "bge-small", "b_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("B", "bge-base",  "b_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("B", "nomic",     "b_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("C", "bge-small", "c_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("C", "bge-base",  "c_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("C", "nomic",     "c_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("D", "bge-small", "d_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("D", "bge-base",  "d_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("D", "nomic",     "d_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
]


def load_probes(yaml_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text())
    by_id = {q["id"]: q for q in data["questions"]}
    return {qid: by_id[qid] for qid in PROBES}


def probe_cell(conn, table: str, probes: dict, embedder: TextEmbedding) -> dict:
    results = {}
    for qid, q in probes.items():
        qvec = list(embedder.embed([q["question"]]))[0].tolist()
        vec_lit = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, original_content FROM factorial.{table} "
                "ORDER BY embedding <=> %s::vector LIMIT 50",
                (vec_lit,),
            )
            rows = cur.fetchall()
        facts = q["required_facts"]
        facts_lower = [f.lower() for f in facts]

        rank_first_gold = None
        top10_hit = False
        top50_hit = False
        matched = set()
        per_fact_rank: dict[str, int] = {}
        for i, (_, original) in enumerate(rows, start=1):
            ol = original.lower()
            for f, fl in zip(facts, facts_lower):
                if fl in ol:
                    if rank_first_gold is None:
                        rank_first_gold = i
                    if i <= 10:
                        matched.add(f)
                        top10_hit = True
                    if i <= 50:
                        top50_hit = True
                    per_fact_rank.setdefault(f, i)

        missed = [f for f in facts if f not in matched]
        per_fact_recall = len(matched) / len(facts) if facts else 0.0
        results[qid] = {
            "rank_of_first_gold_chunk": rank_first_gold,
            "top10_hit": top10_hit,
            "top50_hit": top50_hit,
            "per_fact_recall_at_10": round(per_fact_recall, 4),
            "required_facts_matched": sorted(matched),
            "required_facts_missed": sorted(missed),
        }
    return results


def main():
    root = Path(__file__).resolve().parent.parent
    probes_path = root / "questions" / "scotus.yaml"
    out_dir = root / "results" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)

    dsn = os.environ["AGE_BAKEOFF_PGRG_DSN"]
    probes = load_probes(probes_path)

    # Cache embedders by model_name
    embedders: dict[str, TextEmbedding] = {}
    def get_embedder(model_name: str) -> TextEmbedding:
        if model_name not in embedders:
            print(f"[probe] loading embedder {model_name}", flush=True)
            embedders[model_name] = TextEmbedding(model_name=model_name)
        return embedders[model_name]

    out = {
        "experiment": "factorial-chunking-embedding",
        "corpus": "scotus",
        "probes": list(probes.keys()),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "variants": [],
    }

    with psycopg.connect(dsn) as conn:
        for chunking, embedding, table, model_name, dim in CELLS:
            print(f"[probe] cell {chunking}/{embedding} -> factorial.{table}", flush=True)
            emb = get_embedder(model_name)
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM factorial.{table}")
                n_chunks, n_docs = cur.fetchone()
            per_probe = probe_cell(conn, table, probes, emb)
            out["variants"].append({
                "chunking": chunking,
                "embedding": embedding,
                "table": table,
                "n_chunks": n_chunks,
                "n_docs": n_docs,
                "embed_dim": dim,
                "per_probe": per_probe,
            })

    json_path = out_dir / "factorial-probe.json"
    json_path.write_text(json.dumps(out, indent=2))

    # Build report
    rows = []
    for v in out["variants"]:
        ranks = [v["per_probe"][p]["rank_of_first_gold_chunk"] for p in FAILING_PROBES]
        ranks_num = [r if r is not None else 10_000 for r in ranks]
        avg_rank = sum(ranks_num) / len(ranks_num)
        rows.append((avg_rank, v))
    rows.sort(key=lambda x: x[0])

    def _fmt(r):
        return "∞" if r is None else str(r)

    lines = []
    lines.append("# Factorial Chunking × Embedding Probe Report\n")
    lines.append(f"Generated: {out['generated_at']}\n")
    lines.append(f"Corpus: scotus ({out['variants'][0]['n_docs']} docs)\n")
    lines.append("\n## 12-row table (sorted by avg rank of first gold across 3 failing probes)\n")
    lines.append("| chunking | embedding | n_chunks | avg_rank_failing | q-004 rank | q-008 rank | q-025 rank | q-018 rank (control) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for avg_rank, v in rows:
        pp = v["per_probe"]
        lines.append(
            f"| {v['chunking']} | {v['embedding']} | {v['n_chunks']} | "
            f"{avg_rank:.1f} | "
            f"{_fmt(pp['scotus-q-004']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-008']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-025']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-018']['rank_of_first_gold_chunk'])} |"
        )

    # Baseline: A/bge-small (current production config)
    baseline = next(v for v in out["variants"] if v["chunking"] == "A" and v["embedding"] == "bge-small")
    baseline_lift = sum(
        len(baseline["per_probe"][p]["required_facts_matched"])
        for p in FAILING_PROBES
    )
    lines.append("\n## Decision\n")
    best_avg, best = rows[0]
    best_lift = sum(
        len(best["per_probe"][p]["required_facts_matched"])
        for p in FAILING_PROBES
    )
    delta = best_lift - baseline_lift
    if delta >= 0.3 * baseline_lift and delta >= 2:
        decision = f"ADOPT_CELL={best['chunking']}/{best['embedding']}"
    else:
        decision = "NO_LIFT_NEXT=ENTITY_DRILL"
    lines.append(f"Baseline (A/bge-small) required_facts_matched across failing probes: {baseline_lift}")
    lines.append(f"Best cell ({best['chunking']}/{best['embedding']}) matched: {best_lift}  (Δ={delta:+d})\n")
    lines.append(f"DECISION: {decision}\n")

    md_path = out_dir / "factorial-probe-REPORT.md"
    md_path.write_text("\n".join(lines))
    print(f"[probe] wrote {json_path} and {md_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the probe**

```bash
cd /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff
uv run python scripts/factorial-probe-query.py
cat results/diagnostics/factorial-probe-REPORT.md
```

Expected: JSON and MD reports written; stdout ends with a `DECISION: ...` line.

- [ ] **Step 4: Commit results**

```bash
git add benchmarks/age-bakeoff/scripts/factorial-probe-query.py \
        benchmarks/age-bakeoff/results/diagnostics/factorial-probe.json \
        benchmarks/age-bakeoff/results/diagnostics/factorial-probe-REPORT.md
git rm benchmarks/age-bakeoff/scripts/factorial-probe.py \
       benchmarks/age-bakeoff/tests/test_factorial_probe.py
git commit -m "feat(bakeoff): factorial probe results (SC-002 retrieval root-cause)"
```

---

## Self-review checklist

**Spec coverage:**
- ✅ Multi-source: files, json_corpus, pg_table (live); http, s3 (stubs) — Task 2
- ✅ Chunking: 4 strategies — Task 3
- ✅ Embedding: fastembed-backed, any HF model — Task 4
- ✅ Optional tags extractor: none + rake — Task 5
- ✅ pgvector sink with per-doc incremental writes — Task 6
- ✅ YAML config per cell — Task 1
- ✅ Good CLI help (click with `--help`), README — Tasks 7, 8, 9
- ✅ Process 4 at a time — Task 8 default concurrency
- ✅ 1 CPU core default — Task 7 runtime config
- ✅ 12 configs for the factorial experiment — Task 9
- ✅ Checkpoint polling at 60/120/300/600s — Task 8
- ✅ Smoke then full run — Tasks 10, 11
- ✅ Probe-query tool produces factorial-probe.json + REPORT.md with a DECISION line — Task 12

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `Chunk.doc_id`, `Chunk.seq_num`, `Chunk.original_content`, `Chunk.embedded_content`, `Chunk.metadata` used consistently across sink, runner, probe-query. `CellConfig.runtime.doc_limit` referenced consistently. `TargetConfig.schema_name` aliased to YAML key `schema` everywhere.

**Known risks:**
- fastembed downloads ~3 GB of models on first run (bge-small ~150 MB, bge-base ~430 MB, nomic ~1.3 GB). Account for that in Task 10's smoke time estimate.
- nomic may require `trust_remote_code=True`; if fastembed errors, Task 4 needs a follow-up to pass that flag. Will discover during Task 4's test.
- HNSW index build on a 1337-chunk B table × 768-dim nomic embeddings is ~20s; on full 772-doc C tables it's a few seconds. Negligible compared to embedding time.
- `subprocess.Popen` with `start_new_session=True` means orchestrator-level SIGINT won't kill workers — we rely on the overall_timeout for hung workers. Document this in README.
