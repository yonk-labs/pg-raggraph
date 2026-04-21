"""Microsoft GraphRAG engine adapter — Phase 4 of the multi-corpus bake-off.

Unlike the pgrg and AGE adapters (which consume ``ExtractionOutput`` — a
shared chunker + shared entity extraction), MS GraphRAG does its own
chunking, entity extraction, and indexing. So the adapter interface diverges
from ``engines/base.py`` in one key way:

    async def ingest_raw(documents: list[dict]) -> None
        # documents: [{"id": str, "title": str, "content": str}, ...]

rather than ``async def ingest(extraction: ExtractionOutput) -> None``.

This asymmetry is documented in every benchmark paper's Methodology section
(SC-013 of the multi-corpus mission brief). MS GraphRAG's numbers represent
its full pipeline including its own chunker and embedder; comparability with
pgrg + AGE is at the end-to-end accuracy level, not chunk-for-chunk.

Supported query modes (mapped to MS GraphRAG's native API):
- ``basic``  → ``graphrag.api.basic_search``    (pure vector)
- ``local``  → ``graphrag.api.local_search``    (entity-anchored)
- ``global`` → ``graphrag.api.global_search``   (community-report)
- ``drift``  → ``graphrag.api.drift_search``    (hybrid local + global)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

from age_bakeoff.cost import CostTracker
from age_bakeoff.engines.base import EngineInfo, RetrievalResponse

MsGraphMode = Literal["basic", "local", "global", "drift"]

_BAKEOFF_ROOT = Path(__file__).resolve().parents[3]
_WORK_ROOT = Path(
    os.environ.get("BAKEOFF_MSGRAPH_WORK", _BAKEOFF_ROOT / "corpora" / "msgraph-work")
)


def _settings_yaml(api_key_env: str = "GRAPHRAG_API_KEY") -> str:
    """Return a settings.yaml template calibrated for cheap bake-off use.

    Uses gpt-4.1-mini for extraction + summarization (same model the rest of
    the bake-off uses for answers + judge, so extraction quality is
    comparable). Uses text-embedding-3-small (cheapest OpenAI embedder;
    pgrg + AGE use local fastembed bge-small, so this is the unavoidable
    asymmetry — documented per paper).
    """
    return f"""\
completion_models:
  default_completion_model:
    model_provider: openai
    model: gpt-4.1-mini
    auth_method: api_key
    api_key: ${{{api_key_env}}}
    retry:
      type: exponential_backoff
    concurrent_requests: 10

embedding_models:
  default_embedding_model:
    model_provider: openai
    model: text-embedding-3-small
    auth_method: api_key
    api_key: ${{{api_key_env}}}
    retry:
      type: exponential_backoff
    concurrent_requests: 10

input:
  type: text

chunking:
  type: tokens
  size: 1200
  overlap: 100
  encoding_model: o200k_base

input_storage:
  type: file
  base_dir: "input"

output_storage:
  type: file
  base_dir: "output"

reporting:
  type: file
  base_dir: "logs"

cache:
  type: json
  storage:
    type: file
    base_dir: "cache"

vector_store:
  type: lancedb
  db_uri: output/lancedb
  # text-embedding-3-small emits 1536-dim vectors. MS GraphRAG's
  # validate_config utility can auto-detect this but api.build_index
  # does NOT invoke it — setting explicitly prevents a pyarrow
  # array-length assertion in graphrag_vectors/lancedb.py load_documents.
  vector_size: 1536

embed_text:
  embedding_model_id: default_embedding_model

extract_graph:
  completion_model_id: default_completion_model
  prompt: "prompts/extract_graph.txt"
  entity_types: [organization, person, geo, event]
  max_gleanings: 1

summarize_descriptions:
  completion_model_id: default_completion_model
  prompt: "prompts/summarize_descriptions.txt"
  max_length: 500

extract_graph_nlp:
  text_analyzer:
    extractor_type: regex_english

local_search:
  chat_model_id: default_completion_model
  embedding_model_id: default_embedding_model

global_search:
  chat_model_id: default_completion_model

drift_search:
  chat_model_id: default_completion_model
  embedding_model_id: default_embedding_model

basic_search:
  chat_model_id: default_completion_model
  embedding_model_id: default_embedding_model
"""


class MsGraphEngine:
    """MS GraphRAG adapter. Builds one project per corpus in _WORK_ROOT."""

    def __init__(
        self,
        corpus_id: str,
        mode: MsGraphMode = "local",
        answer_model: str = "gpt-4.1-mini",
        top_k: int = 10,
        response_type: str = "Multiple Paragraphs",
    ):
        self._corpus_id = corpus_id
        self._mode = mode
        self._answer_model = answer_model
        self._top_k = top_k
        self._response_type = response_type

        self._project_dir = _WORK_ROOT / corpus_id
        self._config = None
        self._parquets: dict[str, "pd.DataFrame"] = {}  # lazy-loaded
        self._indexed = False

    def _init_project(self) -> None:
        """One-time project scaffold: settings.yaml + input/ + prompts/.

        Propagates OPENAI_API_KEY → GRAPHRAG_API_KEY in the process env so
        settings.yaml's ``${GRAPHRAG_API_KEY}`` interpolation resolves.
        """
        self._project_dir.mkdir(parents=True, exist_ok=True)
        (self._project_dir / "input").mkdir(exist_ok=True)

        # Key propagation — settings.yaml references ${GRAPHRAG_API_KEY} but
        # .env files don't do variable interpolation across layers, so set it
        # in os.environ directly.
        if "GRAPHRAG_API_KEY" not in os.environ and "OPENAI_API_KEY" in os.environ:
            os.environ["GRAPHRAG_API_KEY"] = os.environ["OPENAI_API_KEY"]

        prompts_dir = self._project_dir / "prompts"
        if not prompts_dir.exists():
            # Use graphrag's default prompt templates via its init command
            subprocess.run(
                [
                    "graphrag",
                    "init",
                    "--root",
                    str(self._project_dir),
                    "--force",
                    "--model",
                    "gpt-4.1-mini",
                    "--embedding",
                    "text-embedding-3-small",
                ],
                check=True,
                input=b"\n\n",  # accept defaults
                capture_output=True,
            )

        # Always (re)write settings.yaml from our template so per-corpus
        # runs don't drift from the template baseline.
        (self._project_dir / "settings.yaml").write_text(_settings_yaml())

        # graphrag init writes a .env with a placeholder GRAPHRAG_API_KEY
        # that load_config picks up and which overrides our process-env
        # value. Overwrite with the real key so auth works.
        api_key = os.environ.get("GRAPHRAG_API_KEY") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        (self._project_dir / ".env").write_text(f"GRAPHRAG_API_KEY={api_key}\n")

    async def ingest_raw(self, documents: list[dict]) -> None:
        """Write documents to project input/ and run MS GraphRAG indexing.

        Each document becomes one .txt file. MS GraphRAG chunks internally.
        """
        self._init_project()

        # Clean prior input + output for deterministic re-runs
        input_dir = self._project_dir / "input"
        for f in input_dir.glob("*.txt"):
            f.unlink()
        output_dir = self._project_dir / "output"
        if output_dir.exists():
            shutil.rmtree(output_dir)

        # Write each document as a .txt
        for doc in documents:
            doc_id = str(doc["id"]).replace("/", "_")
            path = input_dir / f"{doc_id}.txt"
            title = doc.get("title", "")
            body = doc["content"]
            if title:
                path.write_text(f"{title}\n\n{body}", encoding="utf-8")
            else:
                path.write_text(body, encoding="utf-8")

        # Build the index via MS GraphRAG's Python API
        from graphrag import api as graphrag_api
        from graphrag.config.load_config import load_config

        self._config = load_config(self._project_dir)
        await graphrag_api.build_index(config=self._config, verbose=False)
        self._indexed = True
        self._load_parquets()

    def _load_parquets(self) -> None:
        """Load the parquet files MS GraphRAG's indexer emits."""
        import pandas as pd

        output_dir = self._project_dir / "output"
        # File names are stable per MS GraphRAG conventions
        mapping = {
            "entities": "entities.parquet",
            "communities": "communities.parquet",
            "community_reports": "community_reports.parquet",
            "text_units": "text_units.parquet",
            "relationships": "relationships.parquet",
        }
        for key, fname in mapping.items():
            path = output_dir / fname
            self._parquets[key] = (
                pd.read_parquet(path) if path.exists() else pd.DataFrame()
            )

    async def retrieve(self, question: str) -> RetrievalResponse:
        """MS GraphRAG conflates retrieval + answer generation in its query APIs.

        We call the query API, measure total time, and return the source chunks
        it used (from text_units) as the retrieval response. Caller should use
        ``generate_answer`` only as a no-op pass-through — or use
        ``query_end_to_end`` which returns both at once.
        """
        # Stub-ish — most callers use query_end_to_end below. This exists so
        # the adapter implements the Engine protocol's shape.
        t0 = time.perf_counter()
        answer, context = await self._run_query(question)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Extract chunk IDs and content from the context (shape depends on mode)
        chunk_ids, chunk_contents = _chunks_from_context(context)
        return RetrievalResponse(
            retrieved_chunk_ids=chunk_ids,
            retrieved_chunk_contents=chunk_contents,
            retrieval_ms=elapsed_ms,
        )

    async def _run_query(self, question: str) -> tuple[str, dict]:
        from graphrag import api as graphrag_api

        if self._config is None:
            from graphrag.config.load_config import load_config
            self._config = load_config(self._project_dir)
        if not self._parquets:
            self._load_parquets()

        p = self._parquets
        if self._mode == "basic":
            return await graphrag_api.basic_search(
                config=self._config,
                text_units=p["text_units"],
                response_type=self._response_type,
                query=question,
            )
        if self._mode == "local":
            return await graphrag_api.local_search(
                config=self._config,
                entities=p["entities"],
                communities=p["communities"],
                community_reports=p["community_reports"],
                text_units=p["text_units"],
                relationships=p["relationships"],
                covariates=None,
                community_level=2,
                response_type=self._response_type,
                query=question,
            )
        if self._mode == "global":
            return await graphrag_api.global_search(
                config=self._config,
                entities=p["entities"],
                communities=p["communities"],
                community_reports=p["community_reports"],
                community_level=2,
                dynamic_community_selection=False,
                response_type=self._response_type,
                query=question,
            )
        if self._mode == "drift":
            return await graphrag_api.drift_search(
                config=self._config,
                entities=p["entities"],
                communities=p["communities"],
                community_reports=p["community_reports"],
                text_units=p["text_units"],
                relationships=p["relationships"],
                community_level=2,
                response_type=self._response_type,
                query=question,
            )
        raise ValueError(f"Unknown MS GraphRAG mode: {self._mode!r}")

    async def generate_answer(
        self,
        question: str,
        retrieved_contents: list[str],
        tracker: CostTracker | None = None,
    ) -> tuple[str, float]:
        """MS GraphRAG's query API returns the answer already. This method
        accepts the pre-computed answer via retrieved_contents[0] passthrough
        if the caller used query_end_to_end; otherwise re-queries.
        """
        t0 = time.perf_counter()
        answer, _ctx = await self._run_query(question)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return str(answer), elapsed_ms

    async def query_end_to_end(
        self, question: str
    ) -> tuple[str, list[str], float, float]:
        """Single round-trip convenience: returns (answer, chunk_contents,
        retrieval_ms, total_ms). Use this in the runner instead of
        retrieve() + generate_answer() since MS GraphRAG does both in one call.
        """
        t0 = time.perf_counter()
        answer, context = await self._run_query(question)
        total_ms = (time.perf_counter() - t0) * 1000
        _chunk_ids, chunk_contents = _chunks_from_context(context)
        # MS GraphRAG doesn't split retrieval from generation cleanly; report
        # total time for both slots so the runner's schema stays consistent.
        return str(answer), chunk_contents, total_ms, total_ms

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="msgraph",
            embedding_model="text-embedding-3-small",
            answer_model=self._answer_model,
            top_k=self._top_k,
            hop_budget=0,  # MS GraphRAG doesn't expose an explicit hop budget
        )

    async def cleanup(self) -> None:
        """Nothing to clean — project dir persists as a reproducibility artifact."""
        return None


def _chunks_from_context(context: object) -> tuple[list[str], list[str]]:
    """Extract retrieved chunk IDs + contents from MS GraphRAG's context object.

    The context shape varies per mode:
    - basic_search / local_search / drift_search: dict with 'sources' DataFrame
    - global_search: dict with 'reports' DataFrame (no raw chunks)
    """
    ids: list[str] = []
    contents: list[str] = []

    if isinstance(context, dict):
        sources = context.get("sources")
        if sources is not None and hasattr(sources, "to_dict"):
            # DataFrame of text units
            try:
                df = sources
                if "id" in df.columns:
                    ids = df["id"].astype(str).tolist()
                if "text" in df.columns:
                    contents = df["text"].astype(str).tolist()
                elif "chunk" in df.columns:
                    contents = df["chunk"].astype(str).tolist()
            except Exception:
                pass
        # global_search returns community reports, not raw chunks; expose their text
        reports = context.get("reports")
        if (not contents) and reports is not None and hasattr(reports, "to_dict"):
            try:
                if "content" in reports.columns:
                    contents = reports["content"].astype(str).tolist()
                elif "summary" in reports.columns:
                    contents = reports["summary"].astype(str).tolist()
                if "id" in reports.columns:
                    ids = reports["id"].astype(str).tolist()
            except Exception:
                pass

    return ids, contents
