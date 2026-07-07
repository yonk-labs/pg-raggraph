"""pg-raggraph — PostgreSQL-native GraphRAG."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from itertools import islice
from typing import Callable

try:
    __version__ = _pkg_version("pg-raggraph")
except PackageNotFoundError:
    # Editable install without installed metadata (rare). Mirror pyproject.
    __version__ = "0.5.0a19"

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult
from pg_raggraph.profiles import ProfileCalibration, ProfileSpec
from pg_raggraph.resolution import ResolvedEntity

# Canonical extension allowlist for ingestion. Mirrored by the FastAPI server
# and the MCP server so all surfaces accept the same set. Stored as a tuple
# so it's compatible with str.endswith() in the directory walker.
INGEST_ALLOWED_EXTS: tuple[str, ...] = (
    ".md",
    ".txt",
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rst",
)

__all__ = [
    "GraphRAG",
    "INGEST_ALLOWED_EXTS",
    "PGRGConfig",
    "ProfileCalibration",
    "ProfileSpec",
    "QueryResult",
    "ResolvedEntity",
    "__version__",
]

logger = logging.getLogger("pg_raggraph")
metrics_logger = logging.getLogger("pg_raggraph.metrics")


def _json_default(obj):
    """JSON encoder fallback for types stdlib json can't handle natively.

    datetime → ISO 8601 string (queryable from JSONB via
    ``metadata->>'effective_from'``). Falls back to ``str(obj)`` for
    anything else so a user's exotic metadata value never crashes ingest.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


class _JSONLogFormatter(logging.Formatter):
    """Minimal stdlib-only JSON formatter for log aggregator pipelines.

    No extra dep. Output shape matches the common Datadog / ELK / Loki
    expectation: `ts`, `level`, `logger`, `msg`, plus `exc_info` when present.
    Honors `extra={...}` on log calls — anything extra is merged at the top
    level (keeping `ts`, `level`, `logger`, `msg` reserved).
    """

    _RESERVED = frozenset({"ts", "level", "logger", "msg", "exc_info"})

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Merge extras (logger.info("...", extra={"request_id": x}) patterns).
        for k, v in record.__dict__.items():
            if k in self._RESERVED:
                continue
            if k.startswith("_"):
                continue
            if k in (
                "args",
                "msg",
                "name",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "module",
                "filename",
                "pathname",
                "funcName",
                "process",
                "processName",
                "thread",
                "threadName",
                "created",
                "msecs",
                "relativeCreated",
                "levelname",
                "levelno",
                "asctime",
                "message",
                "taskName",
            ):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)
        return json.dumps(payload, default=str)


_logging_configured = False


def _configure_logging() -> None:
    """Idempotent root-logger configuration honoring PGRG_LOG_FORMAT.

    Default (env unset or anything other than "json"): leave existing handlers
    alone — caller's logging setup wins. When PGRG_LOG_FORMAT=json AND no
    handlers are attached to the pg_raggraph logger yet, install a single
    StreamHandler with the JSON formatter at PGRG_LOG_LEVEL (default INFO).
    """
    global _logging_configured
    if _logging_configured:
        return
    fmt = os.environ.get("PGRG_LOG_FORMAT", "").strip().lower()
    if fmt != "json":
        _logging_configured = True
        return
    if logger.handlers:
        # Caller already wired their own handler; respect it.
        _logging_configured = True
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONLogFormatter())
    level_name = os.environ.get("PGRG_LOG_LEVEL", "INFO").upper()
    handler.setLevel(getattr(logging, level_name, logging.INFO))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    _logging_configured = True


_configure_logging()

_NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")
_LIVING_CADENCES = {"hour", "day", "week", "month"}


@dataclass(frozen=True)
class _LivingContext:
    logical_id: str
    cadence: str
    bucket: str
    bucket_start: datetime
    bucket_end: datetime
    source_id: str
    audit_diffs: bool


def _as_aware_utc(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError(
            f"living timestamp must be datetime or ISO string, got {type(value).__name__}"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _living_bucket(ts: datetime, cadence: str) -> tuple[str, datetime, datetime]:
    if cadence not in _LIVING_CADENCES:
        raise ValueError(f"living_cadence must be one of {sorted(_LIVING_CADENCES)}")
    ts = _as_aware_utc(ts)
    if cadence == "hour":
        start = ts.replace(minute=0, second=0, microsecond=0)
        return start.strftime("%Y-%m-%dT%H"), start, start + timedelta(hours=1)
    if cadence == "day":
        start = datetime.combine(ts.date(), dt_time.min, tzinfo=timezone.utc)
        return start.strftime("%Y-%m-%d"), start, start + timedelta(days=1)
    if cadence == "week":
        iso_year, iso_week, _ = ts.isocalendar()
        start_date = datetime.fromisocalendar(iso_year, iso_week, 1).date()
        start = datetime.combine(start_date, dt_time.min, tzinfo=timezone.utc)
        return f"{iso_year}-W{iso_week:02d}", start, start + timedelta(days=7)
    start = datetime(ts.year, ts.month, 1, tzinfo=timezone.utc)
    if ts.month == 12:
        end = datetime(ts.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(ts.year, ts.month + 1, 1, tzinfo=timezone.utc)
    return start.strftime("%Y-%m"), start, end


def _validate_namespace(ns: str) -> None:
    if not _NAMESPACE_RE.match(ns):
        raise ValueError(
            f"Invalid namespace '{ns}'. Must be 1-64 chars, "
            "alphanumeric/hyphens/underscores/dots only."
        )


def _is_graph_ready(summary: dict[str, int]) -> bool:
    """Readiness derivation shared by status()/graph_ready()/wait_for_graph_ready().

    Ready = nothing mid-extraction. 'failed' is a terminal state and does
    not block readiness (issue #92).
    """
    return summary.get("pending", 0) + summary.get("processing", 0) == 0


async def _abatched(records, n: int):
    """Yield lists of up to ``n`` items from ``records``, pulled lazily.

    Accepts a sync iterable (incl. ``list``), a sync generator, or an async
    iterable, and normalizes all three to an async stream of bounded batches —
    without ever materializing the whole input. This is what lets
    ``ingest_records`` hold O(batch_size) records in memory instead of O(N).
    See issue #46.
    """
    if n < 1:
        raise ValueError("batch_size must be >= 1")
    if hasattr(records, "__aiter__"):
        batch: list = []
        async for r in records:
            batch.append(r)
            if len(batch) >= n:
                yield batch
                batch = []
        if batch:
            yield batch
    else:
        it = iter(records)
        while batch := list(islice(it, n)):
            yield batch


class GraphRAG:
    """Main entry point for pg-raggraph.

    Usage:
        async with GraphRAG("postgresql://localhost/mydb") as rag:
            await rag.ingest(["./docs/"])
            result = await rag.query("How does auth work?")
            for chunk in result.chunks:
                print(chunk.content)
    """

    def __init__(self, dsn: str | None = None, *, reranker=None, **kwargs):
        """Construct a GraphRAG instance.

        Args:
            dsn: PostgreSQL connection string. Optional — can also be set
                via PGRG_DSN env var or kwargs["dsn"].
            reranker: Optional Reranker (see pg_raggraph.reranker.Reranker
                protocol) to inject for power users. If None, a
                FastEmbedReranker is lazy-loaded from config.rerank_model
                on first use of rerank=True.
            **kwargs: Any PGRGConfig field. See docs/Config-Reference.md
                for the full list.
        """
        if dsn:
            kwargs["dsn"] = dsn
        self.config = PGRGConfig(**kwargs)
        self._db = None
        self._embedder = None
        self._llm = None  # Shared LLM provider; closed with the instance
        # If user injects a reranker, use it; otherwise lazy-load from
        # config.rerank_model on first rerank=True call.
        self._reranker = reranker
        from pg_raggraph.result_cache import ResultCache

        self._result_cache = ResultCache(self.config.result_cache_size)
        # PR-209: cooperative shutdown signal for long-running ingest loops.
        # Lazily initialized inside ingest() because it must be created on the
        # running asyncio loop, not at __init__ time.
        self._shutdown_event = None

    def request_shutdown(self) -> None:
        """Signal in-progress ingest loops to drain gracefully.

        Already-running per-file transactions finish; queued files become
        no-ops counted as skipped. Safe to call from a SIGTERM/SIGINT handler::

            import asyncio, signal
            from pg_raggraph import GraphRAG

            rag = GraphRAG(...)
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, rag.request_shutdown)

        Idempotent. Safe to call before ingest() starts (no-op).
        """
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def connect(self):
        from pg_raggraph.db import Database, EmbeddingDimMismatch

        self._db = Database(self.config)
        try:
            await self._db.connect()
        except EmbeddingDimMismatch:
            # Surface the actionable config message instead of masking it as a
            # generic connectivity error.
            raise
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to PostgreSQL at {self.config.dsn}. "
                f"Is the database running? Error: {e}"
            ) from e

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
        if self._embedder is not None and hasattr(self._embedder, "aclose"):
            await self._embedder.aclose()
        self._embedder = None
        if self._llm is not None and hasattr(self._llm, "aclose"):
            await self._llm.aclose()
            self._llm = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    @property
    def db(self):
        if self._db is None:
            raise RuntimeError("Not connected. Call connect() or use async with.")
        return self._db

    def _get_embedder(self):
        if self._embedder is None:
            from pg_raggraph.embedding import get_embedding_provider

            self._embedder = get_embedding_provider(self.config)
        return self._embedder

    def _emit_metric(self, event: str, **fields) -> None:
        metrics_logger.info(event, extra={"event": event, **fields})

    @staticmethod
    def _embedding_cache_key(text: str) -> str:
        return sha256(text.encode("utf-8")).hexdigest()

    def _embedding_cache_namespace(self) -> str:
        if self.config.embedding_provider == "http":
            endpoint = self.config.embedding_base_url
        elif self.config.embedding_provider in ("openai", "ollama"):
            endpoint = self.config.llm_base_url
        else:
            endpoint = ""
        raw = (
            f"provider={self.config.embedding_provider}\n"
            f"model={self.config.embedding_model}\n"
            f"dim={self.config.embedding_dim}\n"
            f"endpoint={endpoint.rstrip('/')}"
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    async def _embed_texts_with_cache(self, texts: list[str], embedder) -> list[list[float]]:
        """Embed texts, backed by the process-shared Postgres embedding cache."""
        if not texts:
            return []

        cache_ns = self._embedding_cache_namespace()
        keys = [self._embedding_cache_key(text) for text in texts]
        rows = await self.db.fetch_all(
            "SELECT text_sha256, embedding FROM pgrg_embedding_cache_get(%s, %s::text[])",
            (cache_ns, keys),
        )
        cached = {row["text_sha256"]: row["embedding"] for row in rows}

        miss_keys: list[str] = []
        miss_texts: list[str] = []
        seen = set(cached)
        for key, text in zip(keys, texts):
            if key in seen:
                continue
            seen.add(key)
            miss_keys.append(key)
            miss_texts.append(text)

        if miss_texts:
            miss_embeddings = await embedder.embed(miss_texts)
            async with self.db.transaction() as tx:
                for key, embedding in zip(miss_keys, miss_embeddings):
                    cached[key] = embedding
                    await tx.execute(
                        "SELECT pgrg_embedding_cache_put(%s, %s, %s::vector)",
                        (cache_ns, key, embedding),
                    )

        return [cached[key] for key in keys]

    async def ingest(
        self,
        paths: list[str],
        namespace: str | None = None,
        on_progress=None,
        *,
        metadata: dict | None = None,
    ):
        """Ingest documents from file paths with parallel processing.

        Optimizations:
        - Parallel LLM extraction (extract_concurrency, default 8)
        - Batched entity embeddings (1 call instead of N)
        - Parallel document processing (doc_concurrency, default 4)
        - Content hash dedup

        Args:
            paths: File or directory paths to ingest.
            namespace: Namespace for data isolation.
            on_progress: Optional callback(message: str) for progress updates.
            metadata: Per-ingest evolution hints applied to every file in this
                call. Optional keys: ``effective_from``, ``effective_to``,
                ``retracted``, ``retracted_at``, ``retraction_reason``,
                ``version_label``, ``supersedes_document_id``. When
                ``version_label``, ``supersedes_document_id``, or
                ``retraction_reason`` is present, a ``document_versions`` row
                is also created mirroring the document's evolution metadata.
        """
        import asyncio

        from pg_raggraph.chunking import chunk_document, content_hash
        from pg_raggraph.extraction import extract_from_chunks, get_llm_provider

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        started = time.perf_counter()
        # PR-215: apply nice_level here (was previously in config init,
        # which surprised callers by mutating process priority on import).
        self.config.apply_nice_level()
        embedder = self._get_embedder()

        def _progress(msg: str):
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        # Directories to skip when walking — avoid vendored code, build artifacts,
        # model checkpoints, etc.
        SKIP_DIRS = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "target",  # Rust build
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            ".tox",
            "checkpoints",
            "models",
            ".cargo",
            ".idea",
            ".vscode",
            "site-packages",
            ".autonomy",
            "skill-output",
        }
        SUPPORTED_EXTS = INGEST_ALLOWED_EXTS

        # Collect and validate file paths
        file_paths = []
        for p in paths:
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    # Prune skipped dirs in-place so we don't descend into them
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for f in files:
                        if f.endswith(SUPPORTED_EXTS):
                            file_paths.append(os.path.join(root, f))
            elif os.path.isfile(p):
                file_paths.append(p)
            else:
                raise FileNotFoundError(f"Path not found: {p}")

        if not file_paths:
            logger.warning("No supported files found in provided paths.")
            return

        _progress(f"Found {len(file_paths)} files to process.")

        # PR-209: lazily create the shutdown event on the running loop.
        # request_shutdown() can be called before this without error (no-op);
        # once an ingest is in flight, it observes the event and drains.
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()

        # Process documents in parallel batches
        doc_sem = asyncio.Semaphore(self.config.doc_concurrency)
        # LLM is optional — without it, ingest stores chunks+embeddings only
        # (pure vector RAG mode). Reuse the shared provider if already created
        # so the connection pool is shared across ingest() calls.
        from pg_raggraph.lede_extraction import select_extractor

        llm = None
        lede_fn, _needs_llm = select_extractor(self.config)
        if lede_fn is not None:
            from pg_raggraph.lede_extraction import ensure_lede_available

            ensure_lede_available()
            extract_from_chunks = lede_fn
            _progress(
                f"Extraction via {self.config.fact_extractor}"
                + (
                    " (deterministic, no LLM)."
                    if not _needs_llm
                    else " (LLM + deterministic union)."
                )
            )
        # llm+lede sets both lede_fn AND _needs_llm — it still wants the
        # provider; without one it degrades to its deterministic leg.
        if _needs_llm and not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if lede_fn is None and llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")

        stats = {
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "degraded": 0,
            "entities": 0,
            "rels": 0,
        }

        async def _process_file(idx: int, file_path: str):
            # Retry on transient serialization / deadlock errors from
            # concurrent ingestion. Exponential backoff, max 3 attempts.
            async with doc_sem:
                # PR-209: drain gracefully on shutdown. Files queued behind
                # the semaphore become no-ops once request_shutdown() is
                # observed; in-flight files (already past this check) finish
                # their transaction normally.
                if self._shutdown_event is not None and self._shutdown_event.is_set():
                    stats["skipped"] += 1
                    return
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        r = await self._ingest_one_file(
                            file_path,
                            ns,
                            embedder,
                            llm,
                            content_hash,
                            chunk_document,
                            extract_from_chunks,
                            metadata=metadata,
                        )
                        if r:
                            stats["ingested"] += 1
                            stats["entities"] += r["entities"]
                            stats["rels"] += r["rels"]
                            if r.get("degraded"):
                                stats["degraded"] += 1
                            deg_note = (
                                " (extraction failed, vector-only)" if r.get("degraded") else ""
                            )
                            _progress(
                                f"[{idx}/{len(file_paths)}] "
                                f"{os.path.basename(file_path)}: "
                                f"{r['entities']} entities, {r['rels']} rels{deg_note}"
                            )
                        else:
                            stats["skipped"] += 1
                        return
                    except Exception as e:
                        # Postgres deadlock = SQLSTATE 40P01, serialization = 40001.
                        # Prefer the structured sqlstate attribute (psycopg3) over
                        # string matching, which breaks on non-English PG builds.
                        sqlstate = getattr(e, "sqlstate", None)
                        msg = str(e)
                        transient = sqlstate in ("40P01", "40001") or (
                            sqlstate is None
                            and (
                                "40P01" in msg
                                or "40001" in msg
                                or "deadlock detected" in msg
                                or "could not serialize" in msg
                            )
                        )
                        if transient and attempt < 3:
                            backoff = 0.2 * (2 ** (attempt - 1))
                            logger.info(
                                f"Retry {attempt}/3 after {backoff:.1f}s for "
                                f"{file_path}: {msg[:80]}"
                            )
                            await asyncio.sleep(backoff)
                            continue
                        logger.warning(f"Failed {file_path}: {e}")
                        stats["failed"] += 1
                        return

        with self.db.tenant(ns):
            await asyncio.gather(*[_process_file(i + 1, fp) for i, fp in enumerate(file_paths)])

        notes = []
        if stats["failed"]:
            notes.append(f"{stats['failed']} failed")
        if stats["degraded"]:
            notes.append(f"{stats['degraded']} degraded (vector-only, extraction error)")
        suffix = f", {', '.join(notes)}" if notes else ""
        _progress(
            f"Done: {stats['ingested']} ingested, {stats['skipped']} skipped"
            f"{suffix}. "
            f"{stats['entities']} entities, {stats['rels']} relationships."
        )
        self._emit_metric(
            "pgrg.ingest",
            namespace=ns,
            mode="files",
            latency_ms=(time.perf_counter() - started) * 1000,
            documents=len(file_paths),
            ingested=stats["ingested"],
            skipped=stats["skipped"],
            failed=stats["failed"],
        )

    async def ingest_records(
        self,
        records,
        namespace: str | None = None,
        on_progress=None,
        *,
        max_concurrent_docs: int | None = None,
        living_knowledge: bool | None = None,
        living_key: str | None = None,
        living_cadence: str | None = None,
        living_audit_diffs: bool | None = None,
        defer_extraction: bool = False,
        batch_size: int = 64,
        cross_file_code_graph: bool | None = None,
    ):
        """Ingest documents from in-memory records — no disk roundtrip.

        Use this when your source data lives in another database, an API,
        a queue, or anywhere that's not the filesystem. The classic
        pattern for same-database CRM/ERP pipelines:

            with psycopg.connect(crm_dsn) as conn:
                rows = conn.execute("SELECT note_id, note_text, ... FROM ...").fetchall()
            records = [
                {
                    "text": format_doc(row),
                    "source_id": f"sales_note:{row['note_id']}",
                    "metadata": {"order_id": row["order_id"], "status": row["status"]},
                }
                for row in rows
            ]
            await rag.ingest_records(records, namespace="sales_calls")

        Args:
            records: Iterable of dicts. Each dict must have:
                - ``text`` (str, required): document content
                - ``source_id`` (str, required): stable logical identifier
                  used for content-hash dedup AND stale-doc cleanup. Use a
                  scheme like ``"sales_note:42"`` or ``"jira:PROJ-1234"``.
                  Re-ingesting the same source_id with new text replaces
                  the prior version atomically.
                - ``metadata`` (dict, optional): per-record metadata.
                  Persisted as JSONB on ``documents.metadata`` (queryable
                  via ``metadata->>'foo'``). Evolution-tracking keys
                  (``effective_from``, ``effective_to``, ``retracted``,
                  ``version_label``, ``supersedes_document_id``) are ALSO
                  written to dedicated columns. Other keys are stored only
                  in the JSONB.
                - ``entities`` (list of dict, optional): caller-known
                  entities to seed the graph. Each: ``{"name": "...",
                  "entity_type": "...", "description": "...", "properties":
                  {...}}``. ``name`` is required; the rest are optional.
                  Entity resolution merges these with LLM-extracted
                  entities of the same name. Linked to every chunk.
                - ``relationships`` (list of dict, optional): caller-known
                  graph edges. Each: ``{"src": "EntityName1",
                  "dst": "EntityName2", "rel_type": "...", "weight": 1.0,
                  "description": "...", "properties": {...}}``. ``src``
                  and ``dst`` are required and must match either a
                  caller-supplied or LLM-extracted entity name.
                - ``skip_llm`` (bool, optional, default False): skip LLM
                  extraction for this document. Useful when the caller's
                  known_entities/known_relationships already cover what
                  they care about and the LLM would just add noise / cost.
                - ``defer_extraction`` (bool, optional, default False):
                  store the document with ``graph_status='pending'`` and
                  skip extraction during this call. Chunks + embeddings
                  are still written, so ``naive`` retrieval works
                  immediately; a background worker (``pgrg extract``)
                  drains the queue and populates entities/relationships.
                  Per-record override of the call-level kwarg.
                - ``pre_chunked`` (list of dict, optional): bypass
                  pg-raggraph's chunker AND embedder. Each entry:
                  ``{"content": str, "embedded_content": str (optional),
                  "embedding": list[float] (must match config.embedding_dim),
                  "metadata": dict (optional), "token_count": int (optional)}``.
                  Use when an upstream tool (e.g. chunkshop's full pipeline)
                  already chunked + embedded the document. The ``text``
                  field still drives LLM entity/relationship extraction;
                  set it to a sensible reconstruction of the document.
                  See docs/cookbook/chunkshop-integration.md Pattern C.
            namespace: Namespace for data isolation.
            on_progress: Optional callback(message: str) for progress.
            max_concurrent_docs: Optional per-call document concurrency cap.
                Defaults to ``config.doc_concurrency``.
            living_knowledge: When True, compact high-churn records into one
                materialized full document per logical id per cadence bucket.
                Updates inside the same bucket replace the prior materialized
                document instead of creating duplicate retrievable docs.
            living_key: Record or metadata key containing the logical id.
                Defaults to ``config.living_key`` (``"logical_id"``).
            living_cadence: ``"hour"``, ``"day"``, ``"week"``, or ``"month"``.
                Defaults to ``config.living_cadence`` (``"day"``).
            living_audit_diffs: When True, write hash-level overwrite/supersede
                events to ``living_audit_log``. Audit rows are not embedded or
                retrieved.
            defer_extraction: Batch default. When True, every record stores
                ``graph_status='pending'`` and skips synchronous LLM/lede
                extraction; chunks + embeddings still land so ``naive`` works.
                Drain with ``pgrg extract``. Individual records can override
                via the ``defer_extraction`` record key.
            batch_size: Records are pulled and processed in batches of this
                size, so peak memory is O(batch_size) rather than O(corpus).
                ``records`` may therefore be a generator, a DB cursor, or an
                ``async`` iterator — it is never fully materialized for a
                streamed source. A ``list``/``tuple`` is still validated
                eagerly up front (a bad row raises before any write); a stream
                validates each batch as it is pulled. Lower it to cut the
                memory ceiling of a wrapping service; raise it for throughput.
            cross_file_code_graph: For ``chunk_strategy="chunkshop:symbol_aware"``
                code ingests, resolve CALLS/INHERITS/IMPLEMENTS edges across the
                WHOLE ingest corpus (cross-file), not just within each file (#76).
                Defaults to ``config.cross_file_code_graph`` (False). When True,
                one chunkshop resolver accumulates every doc's symbols/calls
                (O(symbols), not content) and a final pass writes the resolved
                edges; each carries ``resolved_intra_file`` in its properties.

        Returns: same stats shape as ``ingest()``.

        Example (CRM with known FK relationships):

            records = [{
                "text": format_doc(row),
                "source_id": f"sales_note:{row['note_id']}",
                "metadata": {"order_id": row["order_id"], "status": row["status"]},
                "entities": [
                    {"name": row["company_name"], "entity_type": "Customer"},
                    {"name": row["product_name"], "entity_type": "Product"},
                    {"name": row["salesperson_name"], "entity_type": "Salesperson"},
                ],
                "relationships": [
                    {"src": row["company_name"], "dst": row["product_name"],
                     "rel_type": "BOUGHT"},
                    {"src": row["salesperson_name"], "dst": row["company_name"],
                     "rel_type": "SOLD_TO"},
                ],
            } for row in crm_rows]
            await rag.ingest_records(records, namespace="sales_calls")
        """
        import asyncio

        from pg_raggraph.chunking import chunk_document, content_hash
        from pg_raggraph.extraction import extract_from_chunks, get_llm_provider

        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        living_enabled = (
            self.config.living_knowledge if living_knowledge is None else living_knowledge
        )
        effective_living_key = living_key or self.config.living_key
        effective_living_cadence = living_cadence or self.config.living_cadence
        effective_living_audit = (
            self.config.living_audit_diffs if living_audit_diffs is None else living_audit_diffs
        )
        if living_enabled and effective_living_cadence not in _LIVING_CADENCES:
            raise ValueError(f"living_cadence must be one of {sorted(_LIVING_CADENCES)}")
        started = time.perf_counter()
        self.config.apply_nice_level()
        embedder = self._get_embedder()

        # Cross-file code graph (#76): one corpus-wide chunkshop resolver for the
        # whole ingest. Accumulates each symbol_aware doc's symbols/calls (phase
        # 1, O(symbols)); after all docs, finalize() resolves cross-file edges
        # and we write them in one pass. Off by default → per-file/streaming.
        effective_cross_file = (
            self.config.cross_file_code_graph
            if cross_file_code_graph is None
            else cross_file_code_graph
        )
        corpus_code_graph = None
        corpus_run_id = None
        if effective_cross_file:
            import uuid

            from pg_raggraph.chunkshop_bridge import CorpusCodeGraph

            corpus_code_graph = CorpusCodeGraph()
            corpus_run_id = uuid.uuid4().hex

        def _progress(msg: str):
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        def _validate_record(i, rec):
            if not isinstance(rec, dict):
                raise TypeError(f"records[{i}] must be a dict, got {type(rec).__name__}")
            if not rec.get("text"):
                raise ValueError(f"records[{i}] missing required 'text' field")
            if not rec.get("source_id"):
                raise ValueError(f"records[{i}] missing required 'source_id' field")
            if living_enabled:
                meta = rec.get("metadata") or {}
                if not rec.get(effective_living_key) and not meta.get(effective_living_key):
                    raise ValueError(
                        f"records[{i}] missing living logical id key "
                        f"{effective_living_key!r} in record or metadata"
                    )

        # A streamed source (generator / async iterator) is consumed lazily in
        # bounded batches so peak memory stays O(batch_size), not O(corpus). A
        # materialized list/tuple is validated eagerly up front to preserve the
        # historical fail-fast contract: a bad row raises before ANY document is
        # written. Streams validate per-record as they are pulled (issue #46).
        is_stream = hasattr(records, "__aiter__") or not hasattr(records, "__len__")
        total = None
        if not is_stream:
            records = list(records)
            for i, rec in enumerate(records):
                _validate_record(i, rec)
            if not records:
                _progress("No records to process.")
                return
            total = len(records)
            _progress(f"Processing {total} records (in-memory ingest).")
        else:
            _progress("Processing records (streaming ingest, bounded batches).")

        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()

        from pg_raggraph.lede_extraction import select_extractor

        doc_concurrency = (
            self.config.doc_concurrency if max_concurrent_docs is None else max_concurrent_docs
        )
        if doc_concurrency < 1:
            raise ValueError("max_concurrent_docs must be >= 1")
        doc_sem = asyncio.Semaphore(doc_concurrency)
        llm = None
        lede_fn, _needs_llm = select_extractor(self.config)
        if lede_fn is not None:
            from pg_raggraph.lede_extraction import ensure_lede_available

            ensure_lede_available()
            extract_from_chunks = lede_fn
            _progress(
                f"Extraction via {self.config.fact_extractor}"
                + (
                    " (deterministic, no LLM)."
                    if not _needs_llm
                    else " (LLM + deterministic union)."
                )
            )
        # llm+lede sets both lede_fn AND _needs_llm — it still wants the
        # provider; without one it degrades to its deterministic leg.
        if _needs_llm and not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if lede_fn is None and llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")

        stats = {
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "degraded": 0,
            "entities": 0,
            "rels": 0,
        }

        async def _process_record(idx: int, rec: dict):
            async with doc_sem:
                if self._shutdown_event is not None and self._shutdown_event.is_set():
                    stats["skipped"] += 1
                    return
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        rec_meta = rec.get("metadata")
                        rec_entities = rec.get("entities")
                        rec_rels = rec.get("relationships")
                        rec_skip_llm = bool(rec.get("skip_llm", False))
                        rec_defer_extraction = bool(rec.get("defer_extraction", defer_extraction))
                        rec_pre_chunked = rec.get("pre_chunked")
                        rec_code_source_content = rec.get("code_source_content")
                        living_context = None
                        source_id = rec["source_id"]
                        if living_enabled:
                            rec_meta = dict(rec_meta or {})
                            logical_id = str(
                                rec.get(effective_living_key) or rec_meta.get(effective_living_key)
                            )
                            ts = _as_aware_utc(
                                rec.get("living_at")
                                or rec_meta.get("living_at")
                                or rec_meta.get("updated_at")
                                or rec_meta.get("effective_from")
                            )
                            bucket, bucket_start, bucket_end = _living_bucket(
                                ts, effective_living_cadence
                            )
                            source_id = (
                                f"living://{ns}/{logical_id}/{effective_living_cadence}/{bucket}"
                            )
                            rec_meta.update(
                                {
                                    "logical_id": logical_id,
                                    "living_logical_id": logical_id,
                                    "living_source_id": rec["source_id"],
                                    "living_cadence": effective_living_cadence,
                                    "living_bucket": bucket,
                                    "living_current": True,
                                    "effective_from": rec_meta.get("effective_from", bucket_start),
                                    "version_label": rec_meta.get(
                                        "version_label",
                                        f"{effective_living_cadence}:{bucket}",
                                    ),
                                }
                            )
                            living_context = _LivingContext(
                                logical_id=logical_id,
                                cadence=effective_living_cadence,
                                bucket=bucket,
                                bucket_start=bucket_start,
                                bucket_end=bucket_end,
                                source_id=rec["source_id"],
                                audit_diffs=effective_living_audit,
                            )
                        r = await self._ingest_one_content(
                            rec["text"],
                            source_id=source_id,
                            ns=ns,
                            embedder=embedder,
                            llm=llm,
                            content_hash_fn=content_hash,
                            chunk_document_fn=chunk_document,
                            extract_from_chunks_fn=extract_from_chunks,
                            metadata=rec_meta,
                            known_entities=rec_entities,
                            known_relationships=rec_rels,
                            skip_llm_for_this_doc=rec_skip_llm,
                            pre_chunked=rec_pre_chunked,
                            living_context=living_context,
                            defer_extraction=rec_defer_extraction,
                            code_source_content=rec_code_source_content,
                            corpus_code_graph=corpus_code_graph,
                            corpus_run_id=corpus_run_id,
                        )
                        if r:
                            stats["ingested"] += 1
                            stats["entities"] += r["entities"]
                            stats["rels"] += r["rels"]
                            if r.get("degraded"):
                                stats["degraded"] += 1
                            deg_note = (
                                " (extraction failed, vector-only)" if r.get("degraded") else ""
                            )
                            _progress(
                                f"[{idx}/{total if total is not None else '?'}] "
                                f"{rec['source_id']}: "
                                f"{r['entities']} entities, {r['rels']} rels{deg_note}"
                            )
                        else:
                            stats["skipped"] += 1
                        return
                    except Exception as e:
                        sqlstate = getattr(e, "sqlstate", None)
                        msg = str(e)
                        transient = sqlstate in ("40P01", "40001") or (
                            sqlstate is None
                            and (
                                "40P01" in msg
                                or "40001" in msg
                                or "deadlock detected" in msg
                                or "could not serialize" in msg
                            )
                        )
                        if transient and attempt < 3:
                            backoff = 0.2 * (2 ** (attempt - 1))
                            await asyncio.sleep(backoff)
                            continue
                        logger.warning(f"Failed {rec['source_id']}: {e}")
                        stats["failed"] += 1
                        return

        # Pull at most `batch_size` records at a time, process the batch
        # concurrently (capped by doc_sem), then free it before pulling the
        # next. Peak task-graph + per-doc working set is O(batch_size), not
        # O(corpus) — this is the bounded-memory fix for issue #46. The
        # per-document transaction boundary inside _ingest_one_content is
        # unchanged, so a batch is not an all-or-nothing write.
        processed = 0
        with self.db.tenant(ns):
            async for batch in _abatched(records, batch_size):
                if is_stream:
                    for j, rec in enumerate(batch):
                        _validate_record(processed + j, rec)
                await asyncio.gather(
                    *[_process_record(processed + j + 1, rec) for j, rec in enumerate(batch)]
                )
                processed += len(batch)

        # Phase 2 (#76): corpus-wide cross-file resolution. After every doc has
        # been accumulated, resolve once and write the resulting CALLS/INHERITS/
        # IMPLEMENTS edges (intra + cross-file) + their CODE_SYMBOL endpoints.
        if corpus_code_graph is not None and corpus_code_graph.count:
            n_rels = await self._write_corpus_code_graph(ns, corpus_code_graph, corpus_run_id)
            if n_rels:
                stats["rels"] += n_rels
                _progress(f"Cross-file code graph: wrote {n_rels} resolved edges.")

        notes_msg = []
        if stats["failed"]:
            notes_msg.append(f"{stats['failed']} failed")
        if stats["degraded"]:
            notes_msg.append(f"{stats['degraded']} degraded")
        suffix = f", {', '.join(notes_msg)}" if notes_msg else ""
        _progress(
            f"Done: {stats['ingested']} ingested, {stats['skipped']} skipped"
            f"{suffix}. {stats['entities']} entities, {stats['rels']} relationships."
        )
        self._emit_metric(
            "pgrg.ingest",
            namespace=ns,
            mode="records",
            latency_ms=(time.perf_counter() - started) * 1000,
            documents=processed,
            ingested=stats["ingested"],
            skipped=stats["skipped"],
            failed=stats["failed"],
        )

    async def _ingest_one_file(
        self,
        file_path,
        ns,
        embedder,
        llm,
        content_hash_fn,
        chunk_document_fn,
        extract_from_chunks_fn,
        *,
        metadata: dict | None = None,
    ):
        """Read a file from disk and ingest it.

        Thin wrapper over `_ingest_one_content` — for in-memory ingest
        (SQL → pgrg in the same database, no disk roundtrip) call
        `ingest_records` instead, which routes directly to
        `_ingest_one_content`.
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, ValueError):
            logger.warning(f"Skipping non-UTF-8 file: {file_path}")
            return None
        return await self._ingest_one_content(
            content,
            source_id=file_path,
            ns=ns,
            embedder=embedder,
            llm=llm,
            content_hash_fn=content_hash_fn,
            chunk_document_fn=chunk_document_fn,
            extract_from_chunks_fn=extract_from_chunks_fn,
            metadata=metadata,
        )

    async def _ingest_one_content(
        self,
        content: str,
        *,
        source_id: str,
        ns,
        embedder,
        llm,
        content_hash_fn,
        chunk_document_fn,
        extract_from_chunks_fn,
        metadata: dict | None = None,
        known_entities: list[dict] | None = None,
        known_relationships: list[dict] | None = None,
        skip_llm_for_this_doc: bool = False,
        pre_chunked: list[dict] | None = None,
        living_context: _LivingContext | None = None,
        defer_extraction: bool = False,
        code_source_content: str | None = None,
        corpus_code_graph=None,
        corpus_run_id=None,
    ):
        """Ingest a single document from in-memory content with all DB
        writes in a single transaction.

        Using db.transaction() ensures all chunks/entities/relationships for
        one doc commit atomically, and chunk_id from INSERT is immediately
        visible to entity_chunks INSERT on the same connection (no pool
        commit propagation race).

        ``source_id`` serves the same role as ``source_path`` in file-based
        ingest: it's the logical identifier for dedup (combined with
        content_hash) and stale-doc cleanup. Use a stable string —
        e.g. ``"sales_note:42"`` — so re-ingests of the same record
        replace the prior version atomically.

        ``known_entities`` and ``known_relationships`` let callers seed
        the graph with structured edges they already have (e.g. FK-derived
        relationships from a CRM). Each known entity is linked to every
        chunk of the document; each known relationship is linked to the
        first chunk. They merge with LLM-extracted entities/relationships
        via the entity-resolution path — same name across both sources
        resolves to the same row.

        ``metadata`` is now persisted to ``documents.metadata`` JSONB as a
        whole (in addition to the evolution-tracking columns). Query via
        ``metadata->>'foo'`` after ingest.

        ``skip_llm_for_this_doc`` skips LLM extraction for this document
        only — useful when the caller's known_entities/known_relationships
        already cover everything they care about and the LLM would just
        add noise (or cost).

        ``pre_chunked`` lets callers bypass pg-raggraph's chunker AND
        embedder. Use when the chunks + embeddings already exist
        upstream (e.g. chunkshop end-to-end pipeline → pg-raggraph
        graph layer; see docs/cookbook/chunkshop-integration.md
        Pattern C). Each list entry is a dict::

            {
                "content":          "<original chunk text>",          # required
                "embedded_content": "<text given to the embedder>",   # optional
                "embedding":        [float, ...],                     # required (dim)
                "metadata":         {...},                            # optional (merged)
                "token_count":      int,                              # optional
            }

        When ``pre_chunked`` is set, ``content`` is still used as the
        full-document text input for LLM entity/relationship extraction
        — set it to a sensible reconstruction (e.g. join all chunks
        with newlines) so the LLM sees the document.

        ``living_context`` is the records-ingest Living Knowledge policy:
        one materialized document per logical id per cadence bucket, with
        intra-bucket updates replacing the prior full document.
        """
        # Use the source_id as the chunker's path hint so .md/.py-style
        # extension detection still works for callers that pass
        # filename-shaped IDs. For non-filename IDs the chunker falls back
        # to content-based detection (e.g. markdown headings).
        file_path = source_id

        # Delta check (read-only)
        c_hash = content_hash_fn(content)
        existing = await self.db.fetch_one(
            "SELECT id FROM documents WHERE namespace = %s AND content_hash = %s",
            (ns, c_hash),
        )
        if existing:
            logger.debug(f"Skipped (unchanged): {file_path}")
            return None

        # Chunk (no DB) — caller can pre-chunk to bypass pg-raggraph's
        # chunker AND embedder (e.g. chunkshop Pattern C, where the upstream
        # pipeline already chunked + embedded + extracted metadata).
        from pg_raggraph.chunking import token_count as _token_count

        if pre_chunked is not None:
            chunks = []
            chunk_embeddings = []
            for i, pc in enumerate(pre_chunked):
                if "content" not in pc or "embedding" not in pc:
                    raise ValueError(f"pre_chunked[{i}] must include 'content' and 'embedding'")
                emb = pc["embedding"]
                if len(emb) != self.config.embedding_dim:
                    raise ValueError(
                        f"pre_chunked[{i}].embedding has dim {len(emb)} but "
                        f"config.embedding_dim={self.config.embedding_dim}. "
                        "Configure GraphRAG with embedding_dim matching the "
                        "upstream embedder, or re-embed at the upstream layer."
                    )
                body = pc["content"]
                emb_content = pc.get("embedded_content") or body
                meta = dict(pc.get("metadata") or {})
                meta.setdefault("source_path", file_path)
                meta.setdefault("chunk_index", i)
                chunks.append(
                    {
                        "content": body,
                        "embedded_content": emb_content,
                        "token_count": pc.get("token_count") or _token_count(emb_content),
                        "content_hash": pc.get("content_hash") or content_hash_fn(body),
                        "metadata": meta,
                    }
                )
                chunk_embeddings.append(emb)
            if not chunks:
                return {"entities": 0, "rels": 0}
        else:
            chunks = chunk_document_fn(content, source_path=file_path, config=self.config)
            if not chunks:
                return {"entities": 0, "rels": 0}

            # Batch embed all chunks. Use embedded_content so the embedder sees
            # heading prefix (hierarchy strategy) or any future neighbor/summary
            # decoration; for auto strategy this equals content.
            texts = [c["embedded_content"] for c in chunks]
            chunk_embeddings = await self._embed_texts_with_cache(texts, embedder)

        # #75: symbol_aware chunking stashes resolved code edges on chunk[0].
        # Convert them to CODE_SYMBOL entities + CALLS/INHERITS/IMPLEMENTS edges
        # via the same bridge mapper Pattern C uses, and merge into the known
        # graph. Pop unconditionally so the bulky edge list never persists on the
        # chunk row; only materialize on the synchronous (non-deferred) path.
        code_edges = chunks[0]["metadata"].pop("__code_edges__", None) if chunks else None
        _code_lang = chunks[0]["metadata"].get("language") if chunks else None
        if corpus_code_graph is not None:
            # #76 cross-file mode: defer ALL edge resolution to the corpus pass.
            # Accumulate this code doc's symbols/calls into the shared resolver;
            # the per-doc (intra-file) edges in `code_edges` are intentionally
            # dropped — the corpus finalize re-materializes them WITH cross-file
            # edges. Only code docs (symbol_aware chunks carry `language`).
            if _code_lang and not defer_extraction:
                calls = await corpus_code_graph.accumulate(
                    content, source_path=file_path, language=_code_lang
                )
                # Spill this doc's call sites to the staging table so the
                # resolver never holds the whole corpus's calls in memory
                # (#76 OOM fix). Empty when chunkshop isn't spillable — then
                # calls stay in the extractor for a single end-of-ingest pass.
                if calls and corpus_run_id is not None:
                    await self._spill_code_calls(ns, corpus_run_id, calls)
        elif code_edges and not defer_extraction:
            from pg_raggraph import chunkshop_bridge

            _code_entities, _code_rels = chunkshop_bridge.code_edges_to_known_graph(code_edges)
            known_entities = (known_entities or []) + _code_entities
            known_relationships = (known_relationships or []) + _code_rels

        # Extract entities/relationships via LLM (cache reads OK outside txn).
        # If llm is None or skip_llm_for_this_doc is set, skip extraction
        # entirely — pure vector RAG mode (with whatever known_entities /
        # known_relationships the caller provides as the only graph signal).
        # defer_extraction is the new background-extraction opt-in: chunks +
        # embeddings still land (so naive retrieval works), but extraction is
        # deferred to a `pgrg extract` worker that drains graph_status='pending'.
        extraction_degraded = False
        from pg_raggraph.lede_extraction import LEDE_CAPABLE_EXTRACTORS

        _lede_path = getattr(self.config, "fact_extractor", "none") in LEDE_CAPABLE_EXTRACTORS
        if defer_extraction or (llm is None and not _lede_path) or skip_llm_for_this_doc:
            from pg_raggraph.models import ExtractionResult

            extraction_results = [ExtractionResult() for _ in chunks]
        else:
            try:
                extraction_results = await extract_from_chunks_fn(
                    chunks, llm, self.db, self.config
                )
            except Exception as e:
                logger.warning(f"Extraction failed for {file_path}, ingesting as pure vector: {e}")
                from pg_raggraph.models import ExtractionResult

                extraction_results = [ExtractionResult() for _ in chunks]
                extraction_degraded = True

        # Dedupe entities by name, build per-chunk entity/rel lists
        unique_entities = {}
        chunk_to_entities = []
        chunk_to_rels = []

        for i, extraction in enumerate(extraction_results):
            entity_names = []
            for ent in extraction.entities:
                if ent.name not in unique_entities:
                    unique_entities[ent.name] = {
                        "entity_type": ent.entity_type,
                        "description": ent.description,
                        "properties": {},
                        "chunks": [i],
                    }
                else:
                    unique_entities[ent.name]["chunks"].append(i)
                    existing_desc = unique_entities[ent.name]["description"]
                    if ent.description and ent.description not in existing_desc:
                        unique_entities[ent.name]["description"] += " " + ent.description
                entity_names.append(ent.name)
            chunk_to_entities.append(entity_names)
            # 9-tuple shape: (src, dst, rel_type, description, weight,
            # effective_from, effective_to, retracted, retracted_at).
            # LLM-extracted relationships don't carry temporal info → the
            # last four are None/False → INSERT writes NULL/false.
            chunk_to_rels.append(
                [
                    (
                        r.source,
                        r.target,
                        r.rel_type,
                        r.description,
                        r.weight,
                        None,
                        None,
                        False,
                        None,
                    )
                    for r in extraction.relationships
                ]
            )

        # Merge caller-supplied known entities and relationships.
        # Known entities are document-level: linked to every chunk.
        # Known relationships attach to chunk[0] (only one anchor point
        # is needed; graph traversal queries entities, not chunks).
        if known_entities:
            all_chunk_idxs = list(range(len(chunks)))
            for ke in known_entities:
                if not ke.get("name"):
                    raise ValueError("known_entities entries must include a non-empty 'name'")
                name = ke["name"]
                ke_desc = ke.get("description", "") or ""
                ke_type = ke.get("entity_type", "ENTITY")
                if name not in unique_entities:
                    unique_entities[name] = {
                        "entity_type": ke_type,
                        "description": ke_desc,
                        "properties": dict(ke.get("properties") or {}),
                        "chunks": list(all_chunk_idxs),
                    }
                else:
                    # LLM also found this entity. Caller's domain knowledge
                    # WINS on entity_type and (if non-empty) description —
                    # the user explicitly tagged this as a Customer/Product/
                    # whatever, so don't let the LLM's generic "company"
                    # classification overwrite the caller's intent.
                    if ke_type and ke_type != "ENTITY":
                        unique_entities[name]["entity_type"] = ke_type
                    if ke_desc:
                        unique_entities[name]["description"] = ke_desc
                    unique_entities[name].setdefault("properties", {}).update(
                        ke.get("properties") or {}
                    )
                    existing = set(unique_entities[name]["chunks"])
                    existing.update(all_chunk_idxs)
                    unique_entities[name]["chunks"] = sorted(existing)
                # Reflect in chunk_to_entities so entity_chunks links are written.
                for ci in all_chunk_idxs:
                    if name not in chunk_to_entities[ci]:
                        chunk_to_entities[ci].append(name)

        if known_relationships:
            for kr in known_relationships:
                if not (kr.get("src") and kr.get("dst")):
                    raise ValueError("known_relationships entries must include 'src' and 'dst'")
                # Tuple shape: (src, dst, rel_type, description, weight,
                # effective_from, effective_to, retracted, retracted_at,
                # properties).
                # The four temporal fields are optional; absent → NULL in
                # the relationships row. Mirrors documents-level evolution
                # tracking for per-fact granularity (Pattern M, migration 006).
                rel_tuple = (
                    kr["src"],
                    kr["dst"],
                    kr.get("rel_type", "RELATED_TO"),
                    kr.get("description", "") or "",
                    float(kr.get("weight", 1.0)),
                    kr.get("effective_from"),
                    kr.get("effective_to"),
                    bool(kr.get("retracted", False)),
                    kr.get("retracted_at"),
                    kr.get("properties") or {},
                )
                # Anchor on chunk[0] — relationships are document-level.
                chunk_to_rels[0].append(rel_tuple)

        # Batch embed entities (no DB)
        if unique_entities:
            entity_names_list = list(unique_entities.keys())
            entity_texts = [
                f"{name} {unique_entities[name]['description']}" for name in entity_names_list
            ]
            entity_embeddings = await self._embed_texts_with_cache(entity_texts, embedder)
        else:
            entity_names_list = []
            entity_embeddings = []

        # All DB writes in a single transaction
        from pg_raggraph.resolution import resolve_entity

        async with self.db.transaction() as tx:
            # Incremental update: if source_path exists with a DIFFERENT hash,
            # the file has changed. Pick the prior *current* version (the one
            # still open: effective_to IS NULL) and supersede it inside the same
            # transaction as the new insert, so any failure mid-ingest rolls back
            # both halves and the old version stays visible until the new one
            # commits. Two modes:
            #   * evolution_tier == "off" (default) — DELETE the stale doc
            #     (destructive replace, no history, zero storage growth). FK
            #     cascades take care of chunks + provenance joins; call
            #     prune_orphans() afterwards to clean unreferenced entities.
            #   * evolution_tier != "off" — APPEND-ONLY supersede so time-travel
            #     works (#90): close the prior version (set effective_to) and
            #     point the new version at it via document_versions below,
            #     instead of physically deleting it. The retrieval as_of window +
            #     supersession penalty then serve the right version per query.
            # Living-knowledge ingests run their own append-only path further
            # down, so this only switches modes for plain re-ingests.
            keep_history = self.config.evolution_tier != "off" and living_context is None
            supersede_ts = datetime.now(timezone.utc)
            stale = await tx.fetch_one(
                "SELECT id, content_hash, metadata FROM documents "
                "WHERE namespace = %s AND source_path = %s AND content_hash != %s "
                "  AND effective_to IS NULL "
                "ORDER BY effective_from DESC NULLS LAST, id DESC LIMIT 1",
                (ns, file_path, c_hash),
            )
            if stale:
                if keep_history:
                    await tx.execute(
                        "UPDATE documents SET effective_to = COALESCE(effective_to, %s) "
                        "WHERE id = %s",
                        (supersede_ts, stale["id"]),
                    )
                    logger.info(f"Superseded prior version of {file_path} (history retained)")
                else:
                    await tx.execute("DELETE FROM documents WHERE id = %s", (stale["id"],))
                    logger.info(f"Replaced stale version of {file_path}")

            # Insert document with any caller-supplied evolution metadata.
            # ON CONFLICT uses COALESCE so a re-ingest without metadata doesn't
            # clobber previously-stored evolution fields. For `retracted` we
            # distinguish "absent from meta" (preserve prior value) from
            # "explicitly True/False" (apply the caller's value, including
            # un-retracting). COALESCE can't express this for booleans, so we
            # pass a separate `retracted_explicit` flag and gate the SET on it
            # via CASE WHEN.
            meta = metadata or {}
            eff_from = meta.get("effective_from")
            eff_to = meta.get("effective_to")
            retracted_explicit = "retracted" in meta and meta["retracted"] is not None
            # Value for fresh INSERT: the caller's value if explicit, else
            # False (matches the column DEFAULT). On UPDATE the CASE WHEN
            # below decides whether to apply it at all.
            retracted_value = bool(meta["retracted"]) if retracted_explicit else False
            version_label = meta.get("version_label")
            supersedes_doc = meta.get("supersedes_document_id")

            # Append-only supersede (#90): when we kept the prior version above,
            # stamp the new version's effective_from at the supersede boundary
            # (so an as_of *before* the update excludes it) and point it at the
            # closed prior version. Both only default — a caller who supplied
            # effective_from / supersedes_document_id explicitly wins.
            if stale and keep_history:
                if eff_from is None:
                    eff_from = supersede_ts
                if supersedes_doc is None:
                    supersedes_doc = stale["id"]

            # Persist arbitrary caller metadata to documents.metadata JSONB.
            # The dedicated evolution columns (effective_from etc.) ALSO get
            # the same fields, so callers can query either way.
            # Re-ingest merges (caller intent: add new keys, update changed
            # keys, leave untouched keys alone) — implemented via JSONB
            # concat in the ON CONFLICT branch.
            # Use _json_default so datetime values in metadata (e.g.
            # effective_from / effective_to from evolution-tracking ingests)
            # serialize to ISO strings instead of crashing the ingest.
            doc_metadata_json = json.dumps(meta, default=_json_default) if meta else "{}"

            # graph_status: 'pending' when extraction is deferred to a
            # background worker, else 'ready' (matches the migration default
            # and the pre-feature synchronous behavior).
            graph_status_value = "pending" if defer_extraction else "ready"

            doc_id = await tx.insert_returning_id(
                "INSERT INTO documents "
                "(namespace, content_hash, source_path, metadata, "
                " effective_from, effective_to, retracted, version_label, "
                " graph_status) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
                "ON CONFLICT (namespace, content_hash) DO UPDATE "
                "SET source_path = EXCLUDED.source_path, "
                "    metadata = documents.metadata || EXCLUDED.metadata, "
                "    effective_from = COALESCE("
                "EXCLUDED.effective_from, documents.effective_from), "
                "    effective_to = COALESCE("
                "EXCLUDED.effective_to, documents.effective_to), "
                "    retracted = CASE WHEN %s "
                "THEN EXCLUDED.retracted ELSE documents.retracted END, "
                "    version_label = COALESCE("
                "EXCLUDED.version_label, documents.version_label) "
                "RETURNING id",
                (
                    ns,
                    c_hash,
                    file_path,
                    doc_metadata_json,
                    eff_from,
                    eff_to,
                    retracted_value,
                    version_label,
                    graph_status_value,
                    retracted_explicit,
                ),
            )

            # #81: persist raw file content for deferred CODE docs so the code
            # graph (CALLS/INHERITS/IMPLEMENTS) can be rebuilt out-of-band by
            # `pgrg backfill-code-graph`. Gate: deferred + a symbol_aware code
            # doc (those chunks carry `language`). Atomic with the doc — staged
            # content lands iff the doc does. The table is LOGGED so it survives
            # until a later backfill run.
            #
            # The backfill re-parses this content with tree-sitter, so it must be
            # the FAITHFUL original file. On the self-chunked path `content` is
            # exactly that. On the `pre_chunked` reuse path `content` is joined-
            # chunk text (not faithful), so the caller must supply the real source
            # via `code_source_content`; refuse loudly rather than stage garbage
            # the backfill would mis-parse (silent code-graph loss).
            if defer_extraction and _code_lang:
                stage_content = content if pre_chunked is None else code_source_content
                if pre_chunked is not None and not stage_content:
                    raise ValueError(
                        "code doc ingested with pre_chunked must also pass "
                        "code_source_content (the faithful original file) so the "
                        "deferred code graph can be rebuilt"
                    )
                await tx.execute(
                    "INSERT INTO code_backfill_stage "
                    "(document_id, namespace, content, language, source_path) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (document_id) DO UPDATE SET "
                    "  content = EXCLUDED.content, "
                    "  language = EXCLUDED.language, "
                    "  source_path = EXCLUDED.source_path",
                    (doc_id, ns, stage_content, _code_lang, file_path),
                )

            # If caller supplied version info or a supersession edge, create a
            # document_versions row for authoritative multi-version tracking.
            if version_label or supersedes_doc or meta.get("retraction_reason"):
                await tx.execute(
                    "INSERT INTO document_versions "
                    "(namespace, document_id, version_label, effective_from, effective_to, "
                    " supersedes_document_id, retracted, retracted_at, retraction_reason) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        ns,
                        doc_id,
                        version_label,
                        eff_from,
                        eff_to,
                        supersedes_doc,
                        retracted_value,
                        meta.get("retracted_at"),
                        meta.get("retraction_reason"),
                    ),
                )

            if living_context is not None:
                if stale and living_context.audit_diffs:
                    await tx.execute(
                        "INSERT INTO living_audit_log "
                        "(namespace, logical_id, cadence, bucket, source_path, "
                        " old_document_id, new_document_id, old_content_hash, "
                        " new_content_hash, metadata) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                        (
                            ns,
                            living_context.logical_id,
                            living_context.cadence,
                            living_context.bucket,
                            file_path,
                            stale["id"],
                            doc_id,
                            stale["content_hash"],
                            c_hash,
                            json.dumps(
                                {
                                    "event": "overwrite_bucket",
                                    "source_id": living_context.source_id,
                                },
                                default=_json_default,
                            ),
                        ),
                    )

                prior_current = await tx.fetch_all(
                    "SELECT id, content_hash, source_path FROM documents "
                    "WHERE namespace = %s "
                    "  AND metadata->>'living_logical_id' = %s "
                    "  AND metadata->>'living_cadence' = %s "
                    "  AND metadata->>'living_current' = 'true' "
                    "  AND id != %s",
                    (
                        ns,
                        living_context.logical_id,
                        living_context.cadence,
                        doc_id,
                    ),
                )
                for prior in prior_current:
                    await tx.execute(
                        "UPDATE documents "
                        "SET metadata = jsonb_set(metadata, '{living_current}', 'false'::jsonb), "
                        "    effective_to = COALESCE(effective_to, %s) "
                        "WHERE id = %s",
                        (living_context.bucket_start, prior["id"]),
                    )
                    await tx.execute(
                        "INSERT INTO document_versions "
                        "(namespace, document_id, version_label, effective_from, "
                        " effective_to, supersedes_document_id, retracted, metadata) "
                        "VALUES (%s, %s, %s, %s, %s, %s, false, %s::jsonb)",
                        (
                            ns,
                            doc_id,
                            version_label,
                            living_context.bucket_start,
                            living_context.bucket_end,
                            prior["id"],
                            json.dumps(
                                {
                                    "living_logical_id": living_context.logical_id,
                                    "living_cadence": living_context.cadence,
                                    "living_bucket": living_context.bucket,
                                    "event": "new_living_bucket",
                                },
                                default=_json_default,
                            ),
                        ),
                    )
                    if living_context.audit_diffs:
                        await tx.execute(
                            "INSERT INTO living_audit_log "
                            "(namespace, logical_id, cadence, bucket, source_path, "
                            " old_document_id, new_document_id, old_content_hash, "
                            " new_content_hash, metadata) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                            (
                                ns,
                                living_context.logical_id,
                                living_context.cadence,
                                living_context.bucket,
                                file_path,
                                prior["id"],
                                doc_id,
                                prior["content_hash"],
                                c_hash,
                                json.dumps(
                                    {
                                        "event": "new_bucket_supersedes_prior",
                                        "source_id": living_context.source_id,
                                        "prior_source_path": prior["source_path"],
                                    },
                                    default=_json_default,
                                ),
                            ),
                        )

            # Insert all chunks
            chunk_ids = []
            for i, chunk in enumerate(chunks):
                chunk_id = await tx.insert_returning_id(
                    "INSERT INTO chunks "
                    "(document_id, content, embedded_content, embedding, token_count, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        doc_id,
                        chunk["content"],
                        chunk["embedded_content"],
                        chunk_embeddings[i],
                        chunk["token_count"],
                        json.dumps(chunk["metadata"], default=_json_default),
                    ),
                )
                chunk_ids.append(chunk_id)

            if not unique_entities:
                return {"entities": 0, "rels": 0}

            # Resolve and insert entities (tx duck-types the db interface)
            entity_name_to_id = {}
            for name, emb in zip(entity_names_list, entity_embeddings):
                info = unique_entities[name]
                eid = await resolve_entity(
                    name=name,
                    entity_type=info["entity_type"],
                    description=info["description"],
                    embedding=emb,
                    namespace=ns,
                    db=tx,
                    config=self.config,
                    properties=info.get("properties") or {},
                )
                entity_name_to_id[name] = eid

            # Insert entity_chunks links
            for i, chunk_id in enumerate(chunk_ids):
                if i >= len(chunk_to_entities):
                    break
                seen = set()
                for ent_name in chunk_to_entities[i]:
                    if ent_name in seen or ent_name not in entity_name_to_id:
                        continue
                    seen.add(ent_name)
                    await tx.execute(
                        "INSERT INTO entity_chunks (entity_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (entity_name_to_id[ent_name], chunk_id, 1.0),
                    )

            # Insert relationships and their chunk links
            rel_count = 0
            for i, chunk_id in enumerate(chunk_ids):
                if i >= len(chunk_to_rels):
                    break
                for rel in chunk_to_rels[i]:
                    src_id = entity_name_to_id.get(rel[0])
                    dst_id = entity_name_to_id.get(rel[1])
                    if not (src_id and dst_id):
                        continue
                    # Tuple shape: (src_name, dst_name, rel_type, description, weight,
                    # effective_from, effective_to, retracted, retracted_at, properties).
                    # Older callers may still pass 5-tuples; pad optional fields.
                    eff_from = rel[5] if len(rel) > 5 else None
                    eff_to = rel[6] if len(rel) > 6 else None
                    retracted = rel[7] if len(rel) > 7 else False
                    retracted_at = rel[8] if len(rel) > 8 else None
                    properties = rel[9] if len(rel) > 9 and rel[9] else {}
                    # ON CONFLICT … DO UPDATE keeps the row id stable (so
                    # relationship_chunks below still resolves) and merges
                    # the strongest weight. Idempotent across ingests of the
                    # same edge — required since migration 013 made the
                    # (namespace, src_id, dst_id, rel_type) combination
                    # uniquely indexed.
                    rel_id = await tx.insert_returning_id(
                        "INSERT INTO relationships "
                        "(namespace, src_id, dst_id, rel_type, weight, description, "
                        "effective_from, effective_to, retracted, retracted_at, properties) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
                        "ON CONFLICT (namespace, src_id, dst_id, rel_type) DO UPDATE "
                        "SET weight = GREATEST(relationships.weight, EXCLUDED.weight) "
                        "RETURNING id",
                        (
                            ns,
                            src_id,
                            dst_id,
                            rel[2],
                            rel[4],
                            rel[3],
                            eff_from,
                            eff_to,
                            retracted,
                            retracted_at,
                            json.dumps(properties, default=_json_default),
                        ),
                    )
                    await tx.execute(
                        "INSERT INTO relationship_chunks "
                        "(relationship_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (rel_id, chunk_id, 1.0),
                    )
                    rel_count += 1

        return {
            "entities": len(unique_entities),
            "rels": rel_count,
            "degraded": extraction_degraded,
        }

    async def _spill_code_calls(self, ns, run_id, calls) -> None:
        """Spill one doc's cross-file call sites to the staging table (#76 OOM
        fix). One multi-row insert; rows are drained + deleted in phase 2."""
        if not calls:
            return
        await self.db.execute(
            "INSERT INTO code_calls_stage (namespace, run_id, payload) "
            "SELECT %s, %s, x FROM unnest(%s::jsonb[]) AS x",
            (ns, run_id, [json.dumps(c, default=_json_default) for c in calls]),
        )

    async def _persist_code_edges(self, tx, ns, edges) -> int:
        """Map resolved edges → CODE_SYMBOL entities + relationships and upsert
        them (idempotent). Records ``resolved_intra_file`` per edge. Shared by
        the batched call pass and the class-edge pass. Returns rels written."""
        from pg_raggraph import chunkshop_bridge

        entities, rels = chunkshop_bridge.code_edges_to_known_graph(edges)
        if not rels:
            return 0
        name_to_id: dict[str, int] = {}
        for ent in entities:
            row = await tx.fetch_one(
                "INSERT INTO entities "
                "(namespace, name, entity_type, description, properties) "
                "VALUES (%s, %s, 'CODE_SYMBOL', %s, %s::jsonb) "
                "ON CONFLICT (namespace, name) DO UPDATE SET "
                "  description = COALESCE("
                "    NULLIF(entities.description, ''), EXCLUDED.description), "
                "  properties = entities.properties || EXCLUDED.properties "
                "RETURNING id",
                (
                    ns,
                    ent["name"],
                    ent.get("description", "") or "",
                    json.dumps(ent.get("properties") or {}, default=_json_default),
                ),
            )
            name_to_id[ent["name"]] = row["id"]

        written = 0
        for rel in rels:
            src_id = name_to_id.get(rel["src"])
            dst_id = name_to_id.get(rel["dst"])
            if not (src_id and dst_id):
                continue
            props = dict(rel.get("properties") or {})
            resolution = (props.get("evidence") or {}).get("resolution")
            props["resolved_intra_file"] = resolution == "intra_file"
            await tx.execute(
                "INSERT INTO relationships "
                "(namespace, src_id, dst_id, rel_type, weight, description, properties) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) "
                "ON CONFLICT (namespace, src_id, dst_id, rel_type) DO UPDATE SET "
                "  weight = GREATEST(relationships.weight, EXCLUDED.weight), "
                "  properties = relationships.properties || EXCLUDED.properties",
                (
                    ns,
                    src_id,
                    dst_id,
                    rel.get("rel_type", "CALLS"),
                    float(rel.get("weight", 1.0)),
                    rel.get("description", "") or "",
                    json.dumps(props, default=_json_default),
                ),
            )
            written += 1
        return written

    async def _write_corpus_code_graph(
        self, ns, corpus_code_graph, run_id, batch_size=5000
    ) -> int:
        """#76 phase 2: resolve the accumulated corpus and persist its edges.

        Spillable path (default): drain the staging table in keyset batches,
        resolve each batch of call sites against the in-memory symbol index, and
        upsert the resulting edges — so resolver + writer memory stay O(batch),
        never O(corpus call sites). Then resolve the (small) INHERITS/IMPLEMENTS
        set once. Always cleans up the run's staging rows. Falls back to a single
        in-memory finalize when the chunkshop build isn't spillable.

        Each edge records ``resolved_intra_file`` in its properties (the #76
        acceptance criterion). Returns the number of relationships written.
        """
        if not corpus_code_graph.spillable or run_id is None:
            edges = corpus_code_graph.finalize(project_id=ns)
            if not edges:
                return 0
            async with self.db.transaction() as tx:
                return await self._persist_code_edges(tx, ns, edges)

        written = 0
        try:
            last_id = 0
            while True:
                rows = await self.db.fetch_all(
                    "SELECT id, payload FROM code_calls_stage "
                    "WHERE namespace = %s AND run_id = %s AND id > %s "
                    "ORDER BY id LIMIT %s",
                    (ns, run_id, last_id, batch_size),
                )
                if not rows:
                    break
                last_id = rows[-1]["id"]
                calls = [self._decode_profile_value(r["payload"]) for r in rows]
                edges = corpus_code_graph.resolve_batch(calls)
                if edges:
                    async with self.db.transaction() as tx:
                        written += await self._persist_code_edges(tx, ns, edges)

            class_edges = corpus_code_graph.resolve_class_edges()
            if class_edges:
                async with self.db.transaction() as tx:
                    written += await self._persist_code_edges(tx, ns, class_edges)
        finally:
            # Drop the run's transient scratch rows (success or failure).
            await self.db.execute(
                "DELETE FROM code_calls_stage WHERE namespace = %s AND run_id = %s",
                (ns, run_id),
            )
        return written

    def get_cached_result(self, result_id: str) -> QueryResult | None:
        """Return a previously-retained QueryResult (full chunks) by id, or None
        if it was never cached or has been evicted."""
        return self._result_cache.get(result_id)

    def profiles(self) -> dict:
        """Return retrieval profile ladder metadata and calibration estimates."""
        from pg_raggraph.profiles import load_profile_calibration

        return load_profile_calibration().as_dict()

    @staticmethod
    def _decode_profile_value(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    async def _namespace_profile_value(self, namespace: str):
        row = await self.db.fetch_one(
            "SELECT retrieval_profile FROM namespace_settings WHERE namespace = %s",
            (namespace,),
        )
        if not row:
            return None
        return self._decode_profile_value(row.get("retrieval_profile"))

    async def get_namespace_profile(self, namespace: str | None = None) -> dict:
        """Return the persisted retrieval profile default for a namespace."""
        from pg_raggraph.profiles import resolve_profile

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        value = await self._namespace_profile_value(ns)
        if value is None:
            value = self.config.retrieval_profile
            source = "config"
        else:
            source = "namespace"
        spec = resolve_profile(value, default=self.config.retrieval_profile)
        return {
            "namespace": ns,
            "source": source,
            "profile": value,
            "resolved": {
                "name": spec.name,
                "index": spec.index,
                "context_strategy": spec.context_strategy,
                "top_k": spec.top_k,
                "raw": spec.raw,
            },
        }

    async def set_namespace_profile(
        self,
        namespace: str,
        profile: str | int | float,
    ) -> dict:
        """Persist a namespace-specific retrieval profile default."""
        from pg_raggraph.profiles import resolve_profile

        _validate_namespace(namespace)
        spec = resolve_profile(profile, default=self.config.retrieval_profile)
        await self.db.execute(
            """
            INSERT INTO namespace_settings (namespace, retrieval_profile, updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (namespace) DO UPDATE
            SET retrieval_profile = EXCLUDED.retrieval_profile,
                updated_at = now()
            """,
            (namespace, json.dumps(profile)),
        )
        return {
            "namespace": namespace,
            "profile": profile,
            "resolved": {
                "name": spec.name,
                "index": spec.index,
                "context_strategy": spec.context_strategy,
                "top_k": spec.top_k,
                "raw": spec.raw,
            },
        }

    async def clear_namespace_profile(self, namespace: str) -> dict:
        """Remove a namespace-specific retrieval profile default."""
        _validate_namespace(namespace)
        await self.db.execute("DELETE FROM namespace_settings WHERE namespace = %s", (namespace,))
        return {"namespace": namespace, "cleared": True}

    async def query(
        self,
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        *,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        evolution_aware: bool | None = None,
        retracted_behavior: str | None = None,
        supersession_behavior: str | None = None,
        memory_tier: str | None = None,
        retrieval_strategy: str | None = None,
        summary_base_mode: str | None = None,
        profile: str | int | float | None = None,
        top_k: int | None = None,
        rerank: bool = False,
        metadata_filters: dict | None = None,
        trace_emit: Callable[[dict], None] | None = None,
        fusion: str | None = None,
    ) -> QueryResult:
        """Query the knowledge graph.

        Modes:
            smart (default) - confidence-triggered routing (naive → boost → expand)
            naive - vector + BM25 only (fastest)
            naive_boost - naive + 1-hop graph boost re-ranking
            local - vector seed → graph expansion via entity neighbors
            global - relationship-centric retrieval
            hybrid - local + global combined
            summary - run summary_base_mode substrate, then return a
                deterministic lede hint-biased summary in result.summary (no LLM)

        Evolution-aware kwargs (keyword-only):
            as_of: time-travel filter — restrict to documents whose effective
                window contains this timestamp.
            version_filter: restrict to documents with matching version_label.
            evolution_aware: when False, ignore evolution_tier for this query
                (forces classic retrieval). When None, honors config.
            retracted_behavior: per-call override of ``config.retracted_behavior``.
                One of ``"hide"`` / ``"flag"`` / ``"surface_both"``. ``None``
                (default) falls back to the config value. Useful when one
                ``GraphRAG`` instance serves multiple tenants/scenarios that
                each want different retraction policies without mutating
                ``config.retracted_behavior`` under contention.
            supersession_behavior: per-call override of
                ``config.supersession_behavior``. One of ``"hide"`` /
                ``"prefer_new"`` / ``"surface_both"``. ``None`` (default)
                falls back to the config value. Same race-safe shape as
                ``retracted_behavior`` — multi-tenant deployments can
                choose to hide superseded documents per-call without
                mutating the shared config.
            memory_tier: per-call override of ``config.memory_tier`` for
                chunkshop SP-A agent-memory corpora. One of ``"provisional"``
                / ``"consolidated"`` / ``"both"``. ``None`` (default) falls
                back to the config value. Filter applies only to chunks
                whose ``metadata->>'tier'`` is non-NULL; non-memory chunks
                always pass through. See Pattern M in
                ``docs/cookbook/chunkshop-integration.md``.
            retrieval_strategy: per-call override of ``config.retrieval_strategy``.
                One of ``"weighted"`` (today's default), ``"pre_filter"``
                (predicate-first CTE — best for selective WHERE on indexed
                columns), or ``"vector_first"`` (HNSW-seed CTE with
                post-filter — best for broad queries on large
                single-namespace corpora). ``None`` falls back to config.
                Applies to naive/naive_boost modes only — local/global/
                hybrid already pre-narrow via graph traversal and ignore
                this knob.
            profile: retrieval context profile. Accepts named rungs
                (``"cheap"``, ``"balanced"``, ``"accurate"``), integer rung
                indexes, a 0..1 slider float, or ``"raw"`` for legacy classic
                chunk context. ``None`` uses ``config.retrieval_profile``.
            top_k: caller override for retrieval breadth (how many chunks are
                fetched and returned). ``None`` (default) uses the resolved
                profile's ``top_k`` — preserving prior behavior. When set, it
                overrides the profile breadth; the profile still owns
                ``context_strategy``. Must be >= 1. With ``rerank=True`` this is
                the post-rerank target (``top_k * rerank_factor`` candidates are
                fetched first, then trimmed to ``top_k``).
            rerank: when True, fetch top_k * rerank_factor candidates and
                re-rank with a cross-encoder before trimming to top_k.
                Adds ~30-80 ms p50 latency, zero per-query LLM cost.
                Model and factor configured via PGRGConfig.rerank_model
                and rerank_factor.
            fusion: per-call override of ``config.fusion``. ``"linear"``
                (default) preserves weighted-sum scoring; ``"rrf"`` fuses by
                per-leg rank (scale-free). ``None`` falls back to config.
                Applies to ``naive`` and ``hybrid`` modes only.
        """
        from pg_raggraph.context import pack_query_context
        from pg_raggraph.profiles import resolve_profile
        from pg_raggraph.retrieval import query as retrieval_query

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        if top_k is not None and top_k < 1:
            raise ValueError(f"top_k must be >= 1 when provided, got {top_k}")
        namespace_profile = None
        if profile is None:
            namespace_profile = await self._namespace_profile_value(ns)
        profile_spec = resolve_profile(
            profile if profile is not None else namespace_profile,
            default=self.config.retrieval_profile,
        )
        started = time.perf_counter()
        with self.db.tenant(ns):
            embedder = self._get_embedder()
            # Caller-supplied top_k (issue #84) overrides the profile's breadth;
            # the profile still owns context_strategy. None preserves the
            # profile default, keeping prior behavior unchanged.
            retrieval_top_k = top_k if top_k is not None else profile_spec.top_k
            top_k_override = (
                retrieval_top_k * self.config.rerank_factor if rerank else retrieval_top_k
            )
            with self.db.readonly():
                result = await retrieval_query(
                    question=question,
                    db=self.db,
                    embedder=embedder,
                    config=self.config,
                    mode=mode,
                    namespace=ns,
                    as_of=as_of,
                    version_filter=version_filter,
                    evolution_aware=evolution_aware,
                    retracted_behavior=retracted_behavior,
                    supersession_behavior=supersession_behavior,
                    memory_tier=memory_tier,
                    retrieval_strategy=retrieval_strategy,
                    summary_base_mode=summary_base_mode,
                    top_k_override=top_k_override,
                    metadata_filters=metadata_filters,
                    trace_emit=trace_emit,
                    fusion=fusion,
                )
            if rerank:
                from pg_raggraph.reranker import FastEmbedReranker, apply_reranker

                if self._reranker is None:
                    self._reranker = FastEmbedReranker(self.config.rerank_model)
                result = await apply_reranker(self._reranker, question, result, retrieval_top_k)
            with self.db.readonly():
                packed = await pack_query_context(
                    question=question,
                    result=result,
                    db=self.db,
                    namespace=ns,
                    profile=profile_spec,
                    config=self.config,
                )
            result.context = packed.text
            # Background-extraction status hint. Lets callers see whether the
            # graph is still backfilling (`pending > 0`) without changing the
            # retrieval result shape. Read-only, single GROUP BY — cheap.
            with self.db.readonly():
                result.metadata["graph_status_summary"] = await self._graph_status_summary(ns)
            self._emit_metric(
                "pgrg.query",
                namespace=ns,
                mode=mode,
                latency_ms=(time.perf_counter() - started) * 1000,
                top_k=len(result.chunks),
                rerank=rerank,
                retrieval_profile=profile_spec.name,
                context_strategy=profile_spec.context_strategy,
            )
            return result

    async def ask(
        self,
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        *,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        evolution_aware: bool | None = None,
        retracted_behavior: str | None = None,
        supersession_behavior: str | None = None,
        memory_tier: str | None = None,
        retrieval_strategy: str | None = None,
        summary_base_mode: str | None = None,
        profile: str | int | float | None = None,
        top_k: int | None = None,
        short_answer: bool = False,
        rerank: bool = False,
        metadata_filters: dict | None = None,
        trace_emit: Callable[[dict], None] | None = None,
        fusion: str | None = None,
    ) -> QueryResult:
        """Query + LLM answer synthesis.

        Runs retrieval then generates a grounded natural-language answer
        using the configured LLM. Falls back to a top-chunk summary if no
        LLM is configured — library stays useful as pure vector RAG.

        When ``short_answer=True``, the LLM is asked for a short factoid
        answer (≤10 tokens, single phrase) instead of a paragraph. Useful
        for SQuAD-style benchmarks where gold answers are short strings.

        When ``rerank=True``, the retrieved chunks are re-ranked with a
        cross-encoder before answer generation. Adds ~30-80 ms p50 latency,
        zero per-query LLM cost.

        ``retracted_behavior``, ``supersession_behavior``, and ``memory_tier``
        override the matching ``config.*`` fields for this call only — see
        ``GraphRAG.query()`` for details. ``top_k`` overrides the resolved
        profile's retrieval breadth for this call; ``None`` keeps the profile
        default.
        """
        from pg_raggraph.answer import generate_answer

        result = await self.query(
            question,
            mode=mode,
            namespace=namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            summary_base_mode=summary_base_mode,
            profile=profile,
            top_k=top_k,
            rerank=rerank,
            metadata_filters=metadata_filters,
            trace_emit=trace_emit,
            fusion=fusion,
        )
        # Reuse the shared LLM client (same pool as ingestion).
        llm = None
        if self.config.llm_base_url:
            if self._llm is None:
                try:
                    from pg_raggraph.extraction import get_llm_provider

                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable: {e}")
            llm = self._llm
        result.answer = await generate_answer(
            question, result, llm, self.config, short_answer=short_answer
        )
        # #2 response shape: for summary mode, assign a stable id, cache the
        # full result for "ask for more", and append the escalation affordance.
        if mode == "summary" and result.chunks:
            import uuid

            result.result_id = uuid.uuid4().hex
            self._result_cache.put(result.result_id, result)
            if self.config.summary_escalation and result.answer:
                result.answer = (
                    f"{result.answer}\n\n---\n"
                    f"{len(result.chunks)} source chunks retained "
                    f"(result_id={result.result_id}). If this doesn't fully answer "
                    f"your question, request the full sources with that id."
                )
        return result

    async def recommend_metadata_indexes(
        self,
        *,
        table: str | None = None,
        sample_size: int = 10_000,
        max_keys: int = 50,
        max_recommendations: int = 20,
    ) -> list:
        """Scan ``chunks.metadata`` + ``documents.metadata`` and return
        ranked index suggestions.

        For sales-notes / structured-DB ingest patterns, the most
        useful indexes typically live on ``documents.metadata`` (where
        caller-supplied fields like salesperson / product / date
        land). This call scans BOTH tables by default; set
        ``table="chunks"`` or ``table="documents"`` to scope.

        Returns a list of ``IndexRecommendation`` dataclasses. A UI
        renders each as a row with table, key, kind, type, rationale,
        and an "Apply" button that calls ``add_metadata_index()``.
        Recommendations with ``already_exists=True`` surface so the
        UI can show "Already applied" instead of dropping them.

        Read-only; safe to call repeatedly. Sample queries are bounded
        by ``sample_size`` (default 10K per key).
        """
        from pg_raggraph.index_management import recommend

        return await recommend(
            self.db,
            table=table,  # type: ignore[arg-type]
            sample_size=sample_size,
            max_keys=max_keys,
            max_recommendations=max_recommendations,
        )

    async def add_metadata_index(
        self,
        key: str,
        *,
        kind: str = "btree",
        sql_type: str | None = None,
        table: str = "chunks",
    ) -> dict:
        """Create one metadata index at runtime, without restart.

        Args:
            key: JSONB key to index. Validated against the same
                identifier whitelist as the config-driven paths.
            kind: ``"btree"`` (per-key on ``metadata->>'<key>'``),
                ``"gin"`` (one index covering the whole JSONB; ``key``
                is ignored), or ``"generated"`` (typed STORED column +
                btree — requires ``sql_type``).
            sql_type: For ``kind="generated"``: one of ``text``,
                ``int``, ``bigint``, ``numeric``, ``timestamptz``,
                ``boolean``. Required for that kind only.
            table: ``"chunks"`` (default — back-compat with the
                chunks-only config knobs) or ``"documents"`` (where
                caller-supplied per-record fields like salesperson /
                product live).

        Returns ``{"ok": bool, "table": ..., "kind": ..., "key": ...,
        "object_name": ..., "error": ...}``. Never raises — failures
        come back as ``ok=False`` so a UI can render them as a row
        error without try/except.
        """
        from pg_raggraph.index_management import add

        return await add(
            self.db,
            key,
            kind=kind,  # type: ignore[arg-type]
            sql_type=sql_type,
            table=table,  # type: ignore[arg-type]
        )

    async def remove_metadata_index(
        self,
        key: str,
        *,
        kind: str = "btree",
        table: str = "chunks",
    ) -> dict:
        """Drop a metadata index (and the column for
        ``kind="generated"``).

        Idempotent — uses ``IF EXISTS`` so a no-op drop returns
        ``ok=True``. ``kind="gin"`` ignores ``key`` (one GIN per
        table). Same return shape as ``add_metadata_index()``.
        """
        from pg_raggraph.index_management import remove

        return await remove(
            self.db,
            key,
            kind=kind,  # type: ignore[arg-type]
            table=table,  # type: ignore[arg-type]
        )

    async def list_metadata_indexes(
        self,
        *,
        table: str | None = None,
    ) -> list[dict]:
        """Snapshot of currently-installed metadata indexes.

        Returns ``[{"name": ..., "definition": ..., "table": ...}, ...]``
        for both tables by default; filter by ``table=`` when needed.
        UI uses this for the "Applied" list / drop confirmation.
        """
        from pg_raggraph.index_management import list_existing_metadata_indexes

        return await list_existing_metadata_indexes(
            self.db,
            table=table,  # type: ignore[arg-type]
        )

    async def apply_metadata_indexes_concurrently(self) -> list[dict]:
        """Create the configured metadata indexes using
        ``CREATE INDEX CONCURRENTLY`` so they don't block writes.

        **Production retrofit path.** Use from a separate maintenance
        script, NOT during application startup. The default
        ``connect()`` flow uses non-concurrent CREATE INDEX which
        takes an ACCESS EXCLUSIVE lock — fine on fresh deployments
        but blocks all writes on live tables with millions of rows.

        Typical flow:

        1. Deploy a config update adding keys to ``metadata_indexes`` /
           ``document_metadata_indexes`` / ``metadata_indexes_gin`` /
           ``document_metadata_indexes_gin``. Don't restart the app yet
           (the non-concurrent path in ``connect()`` would fire).
        2. From a maintenance shell or one-off job::

               rag = GraphRAG(...)
               await rag.connect()  # skips empty config slots
               results = await rag.apply_metadata_indexes_concurrently()
               for r in results:
                   print(r)
               await rag.close()

        3. After it returns, restart the app normally. ``connect()``'s
           ``IF NOT EXISTS`` finds the indexes and is a no-op.

        **Generated columns are NOT supported** by this method —
        Postgres doesn't have a concurrent ``ADD COLUMN`` variant.
        Add those via the connect-time path during a maintenance
        window. The returned list reports each generated-column key
        with ``ok=False`` so the operator sees what was skipped.

        Returns a list of dicts (one per attempted index) with
        ``{"ok": bool, "table": ..., "kind": ..., "key": ...,
        "object_name": ..., "error": ...}``. Same shape as
        ``rag.add_metadata_index()`` so callers can render results
        uniformly.

        See ``docs/cookbook/metadata-indexes.md`` → "Production
        retrofit guide" for the full recipe.
        """
        return await self.db.apply_metadata_indexes_concurrently()

    async def status(self, namespace: str | None = None) -> dict:
        """Get graph statistics, including background-extraction status counts."""
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        with self.db.tenant(ns):
            graph_status = await self._graph_status_summary(ns)
            return {
                "schema_version": int(await self.db.get_meta("schema_version") or 0),
                "embedding_dim": int(await self.db.get_meta("embedding_dim") or 0),
                "namespace": ns,
                "documents": await self.db.count("documents", ns),
                # Chunks table has no namespace column — scope via documents join.
                "chunks": (
                    await self.db.fetch_one(
                        "SELECT count(*) AS cnt FROM chunks c "
                        "JOIN documents d ON d.id = c.document_id "
                        "WHERE d.namespace = %s",
                        (ns,),
                    )
                )["cnt"],
                "entities": await self.db.count("entities", ns),
                "relationships": await self.db.count("relationships", ns),
                "graph_status": graph_status,
                # Derived readiness flag (issue #92): True when no doc is
                # mid-extraction. 'failed' docs are terminal and don't block.
                "graph_ready": _is_graph_ready(graph_status),
            }

    async def graph_ready(self, namespace: str | None = None) -> bool:
        """Cheap probe: is background extraction done for this namespace?

        Returns True when no document is ``'pending'`` or ``'processing'``
        (issue #92). ``'failed'`` docs are terminal and do NOT block
        readiness — inspect ``status()['graph_status']['failed']`` and retry
        via ``pgrg extract --include-failed`` if you care about them.

        Caveat: an empty namespace is trivially ready. During a batched
        ingest, docs not yet written are invisible — check
        ``status()['documents']`` against your expected corpus size if you
        need "did everything land?" rather than "has the queue drained?".
        """
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        with self.db.tenant(ns):
            return _is_graph_ready(await self._graph_status_summary(ns))

    async def wait_for_graph_ready(
        self,
        namespace: str | None = None,
        *,
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ) -> dict[str, int]:
        """Block until background extraction has drained for the namespace.

        Polls the per-status doc counts every ``poll_interval`` seconds until
        no document is ``'pending'`` or ``'processing'``, then returns the
        final summary, e.g. ``{'pending': 0, 'processing': 0, 'ready': 660,
        'failed': 0}``. Raises ``TimeoutError`` (message includes the
        last-seen summary) if the queue hasn't drained within ``timeout``
        seconds.

        This is the first-class "is ingest done?" primitive (issue #92) —
        replaces hand-rolled SQL polling of ``documents.graph_status``::

            await rag.ingest_records(records, namespace="crm", defer_extraction=True)
            summary = await rag.wait_for_graph_ready(namespace="crm")
            if summary["failed"]:
                ...  # pgrg extract --include-failed

        Same caveats as :meth:`graph_ready`: 'failed' is terminal (doesn't
        block), and an empty namespace returns immediately.
        """
        import asyncio

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        deadline = time.monotonic() + timeout
        while True:
            with self.db.tenant(ns):
                summary = await self._graph_status_summary(ns)
            if _is_graph_ready(summary):
                return summary
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"graph not ready in namespace {ns!r} after {timeout}s: {summary}"
                )
            await asyncio.sleep(min(poll_interval, remaining))

    async def _graph_status_summary(self, namespace: str) -> dict[str, int]:
        """Per-status doc count for the namespace.

        Returns all four lifecycle keys (pending/processing/ready/failed) so
        callers can rely on the shape without defaulting. The partial index
        on (namespace, created_at) WHERE graph_status='pending' keeps the
        common 'pending > 0' check cheap; the full GROUP BY scans the
        documents table but is sub-ms at typical sizes.
        """
        rows = await self.db.fetch_all(
            "SELECT graph_status, COUNT(*) AS n FROM documents "
            "WHERE namespace = %s GROUP BY graph_status",
            (namespace,),
        )
        summary = {"pending": 0, "processing": 0, "ready": 0, "failed": 0}
        for row in rows:
            key = row["graph_status"]
            if key in summary:
                summary[key] = int(row["n"])
        return summary

    async def code_impact(
        self,
        fqn: str,
        *,
        namespace: str | None = None,
        depth: int = 1,
        min_confidence: float = 0.0,
    ):
        """Callers and callees of a CODE_SYMBOL by FQN. Returns a CodeImpact.

        See pg_raggraph.code_graph. Namespace defaults to the configured one.
        """
        from pg_raggraph.code_graph import code_impact as _code_impact

        ns = namespace or self.config.namespace
        return await _code_impact(
            self.db, fqn, namespace=ns, depth=depth, min_confidence=min_confidence
        )

    async def delete(self, namespace: str):
        """Delete all data in a namespace."""
        _validate_namespace(namespace)
        with self.db.tenant(namespace):
            async with self.db.transaction() as tx:
                await tx.execute(
                    "DELETE FROM document_versions WHERE namespace = %s",
                    (namespace,),
                )
                await tx.execute("DELETE FROM facts WHERE namespace = %s", (namespace,))
                await tx.execute("DELETE FROM relationships WHERE namespace = %s", (namespace,))
                await tx.execute("DELETE FROM entities WHERE namespace = %s", (namespace,))
                await tx.execute("DELETE FROM documents WHERE namespace = %s", (namespace,))

    async def export_namespace(self, namespace: str):
        """Yield documents and chunks for a namespace."""
        _validate_namespace(namespace)
        with self.db.tenant(namespace):
            rows = await self.db.fetch_all(
                "SELECT d.id AS document_id, d.content_hash, d.source_path, "
                "d.metadata AS document_metadata, d.effective_from, d.effective_to, "
                "d.retracted, d.version_label, d.created_at AS document_created_at, "
                "c.id AS chunk_id, c.content, c.embedded_content, c.token_count, "
                "c.metadata AS chunk_metadata, c.created_at AS chunk_created_at "
                "FROM documents d "
                "LEFT JOIN chunks c ON c.document_id = d.id "
                "WHERE d.namespace = %s "
                "ORDER BY d.id, c.id",
                (namespace,),
            )

        current_id = None
        current_doc = None
        for row in rows:
            if row["document_id"] != current_id:
                if current_doc is not None:
                    yield current_doc
                current_id = row["document_id"]
                current_doc = {
                    "namespace": namespace,
                    "document_id": row["document_id"],
                    "content_hash": row["content_hash"],
                    "source_path": row["source_path"],
                    "metadata": row["document_metadata"] or {},
                    "effective_from": row["effective_from"],
                    "effective_to": row["effective_to"],
                    "retracted": row["retracted"],
                    "version_label": row["version_label"],
                    "created_at": row["document_created_at"],
                    "chunks": [],
                }
            if row["chunk_id"] is not None:
                current_doc["chunks"].append(
                    {
                        "chunk_id": row["chunk_id"],
                        "content": row["content"],
                        "embedded_content": row["embedded_content"],
                        "token_count": row["token_count"],
                        "metadata": row["chunk_metadata"] or {},
                        "created_at": row["chunk_created_at"],
                    }
                )
        if current_doc is not None:
            yield current_doc

    async def delete_document(self, source_path: str, namespace: str | None = None) -> int:
        """Delete a document and all its chunks by source path.

        Entities and relationships are left in place — they may be referenced
        by other documents. Use `prune_orphans()` to clean up any entities
        that become unreferenced.

        Returns number of documents deleted.
        """
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        with self.db.tenant(ns):
            result = await self.db.fetch_one(
                "DELETE FROM documents WHERE namespace = %s AND source_path = %s RETURNING id",
                (ns, source_path),
            )
        return 1 if result else 0

    async def retract(
        self,
        *,
        doc_id: int | None = None,
        source_path: str | None = None,
        reason: str = "",
        retracted_at: datetime | None = None,
        namespace: str | None = None,
    ) -> dict:
        """Mark already-ingested document(s) retracted, post-hoc.

        Exactly one of ``doc_id`` / ``source_path``. By ``source_path`` this
        fans out to every document in the namespace sharing that path
        (DEC-7). Idempotent: retracting an already-retracted document is a
        no-op success. ``retracted_at`` must be timezone-aware (defaults to
        ``now(timezone.utc)``).

        Returns ``{"retracted_count": int}`` — documents matched.
        """
        if (doc_id is None) == (source_path is None):
            raise ValueError("exactly one of doc_id / source_path is required")
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        if retracted_at is None:
            retracted_at = datetime.now(timezone.utc)
        elif retracted_at.tzinfo is None:
            raise ValueError(
                "retracted_at must be timezone-aware "
                "(e.g., datetime(..., tzinfo=timezone.utc)); "
                "naive datetimes silently misbehave against timestamptz columns"
            )

        with self.db.tenant(ns):
            async with self.db.transaction() as tx:
                if doc_id is not None:
                    target_rows = await tx.fetch_all(
                        "SELECT id FROM documents WHERE id = %s AND namespace = %s",
                        (doc_id, ns),
                    )
                else:
                    target_rows = await tx.fetch_all(
                        "SELECT id FROM documents WHERE namespace = %s AND source_path = %s",
                        (ns, source_path),
                    )
                ids = [r["id"] for r in target_rows]
                if not ids:
                    return {"retracted_count": 0}

                await tx.execute(
                    "UPDATE documents SET retracted = true WHERE id = ANY(%s)",
                    (ids,),
                )
                updated = await tx.fetch_all(
                    "UPDATE document_versions "
                    "SET retracted = true, retracted_at = %s, retraction_reason = %s "
                    "WHERE document_id = ANY(%s) RETURNING document_id",
                    (retracted_at, reason, ids),
                )
                have_version = {r["document_id"] for r in updated}
                for mid in (i for i in ids if i not in have_version):
                    await tx.execute(
                        "INSERT INTO document_versions "
                        "(namespace, document_id, retracted, retracted_at, "
                        " retraction_reason) "
                        "VALUES (%s, %s, true, %s, %s)",
                        (ns, mid, retracted_at, reason),
                    )

        return {"retracted_count": len(ids)}

    async def supersede(
        self,
        *,
        old_doc_id: int | None = None,
        old_source_path: str | None = None,
        new_doc_id: int | None = None,
        new_source_path: str | None = None,
        reason: str | None = None,
        effective_at: datetime | None = None,
        namespace: str | None = None,
    ) -> dict:
        """Record that ``new`` supersedes ``old``, post-hoc.

        Exactly one of ``*_doc_id`` / ``*_source_path`` per side. A
        ``*_source_path`` that resolves to != 1 document raises ValueError
        (the supersession pointer is document->document; DEC-7). ``reason``
        is stored in ``document_versions.metadata`` as ``supersede_reason``
        (DEC-8). ``effective_at`` must be timezone-aware (defaults to
        ``now(timezone.utc)``); it is written as the old document's
        ``effective_to`` so existing temporal / ``supersession_behavior``
        logic applies with no new query-path code.

        Returns ``{"updated": int}``.
        """
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        if effective_at is None:
            effective_at = datetime.now(timezone.utc)
        elif effective_at.tzinfo is None:
            raise ValueError(
                "effective_at must be timezone-aware "
                "(e.g., datetime(..., tzinfo=timezone.utc)); "
                "naive datetimes silently misbehave against timestamptz columns"
            )
        # Eager arg-shape validation (DEC-9a): fail fast on a malformed call
        # with zero DB work, for BOTH sides, before opening the transaction —
        # consistent with retract()'s pre-transaction validation. DB
        # resolution (not-found / source_path->!=1) still happens in _resolve.
        if (old_doc_id is None) == (old_source_path is None):
            raise ValueError("exactly one of old_doc_id / old_source_path is required")
        if (new_doc_id is None) == (new_source_path is None):
            raise ValueError("exactly one of new_doc_id / new_source_path is required")

        with self.db.tenant(ns):
            async with self.db.transaction() as tx:

                async def _resolve(side: str, did: int | None, spath: str | None) -> int:
                    if (did is None) == (spath is None):
                        raise ValueError(
                            f"exactly one of {side}_doc_id / {side}_source_path is required"
                        )
                    if did is not None:
                        row = await tx.fetch_one(
                            "SELECT id FROM documents WHERE id = %s AND namespace = %s",
                            (did, ns),
                        )
                        if row is None:
                            raise ValueError(
                                f"{side} document id {did} not found in namespace {ns!r}"
                            )
                        return row["id"]
                    rows = await tx.fetch_all(
                        "SELECT id FROM documents WHERE namespace = %s AND source_path = %s",
                        (ns, spath),
                    )
                    if len(rows) != 1:
                        raise ValueError(
                            f"{side}_source_path {spath!r} resolved to "
                            f"{len(rows)} documents (need exactly 1); pass "
                            f"{side}_doc_id to disambiguate"
                        )
                    return rows[0]["id"]

                old_id = await _resolve("old", old_doc_id, old_source_path)
                new_id = await _resolve("new", new_doc_id, new_source_path)
                if old_id == new_id:
                    raise ValueError("old and new resolve to the same document")

                existing = await tx.fetch_one(
                    "SELECT id FROM document_versions WHERE document_id = %s "
                    "AND retracted = false ORDER BY id DESC LIMIT 1",
                    (new_id,),
                )
                if existing is not None:
                    if reason is not None:
                        await tx.execute(
                            "UPDATE document_versions "
                            "SET supersedes_document_id = %s, "
                            "    metadata = COALESCE(metadata, '{}'::jsonb) "
                            "              || %s::jsonb "
                            "WHERE id = %s",
                            (
                                old_id,
                                json.dumps({"supersede_reason": reason}),
                                existing["id"],
                            ),
                        )
                    else:
                        await tx.execute(
                            "UPDATE document_versions "
                            "SET supersedes_document_id = %s WHERE id = %s",
                            (old_id, existing["id"]),
                        )
                else:
                    meta_json = (
                        json.dumps({"supersede_reason": reason}) if reason is not None else "{}"
                    )
                    await tx.execute(
                        "INSERT INTO document_versions "
                        "(namespace, document_id, supersedes_document_id, metadata) "
                        "VALUES (%s, %s, %s, %s::jsonb)",
                        (ns, new_id, old_id, meta_json),
                    )

                updated = await tx.fetch_all(
                    "UPDATE documents SET effective_to = %s WHERE id = %s RETURNING id",
                    (effective_at, old_id),
                )

        return {"updated": len(updated)}

    async def delete_entity(self, entity_id: int) -> bool:
        """Delete an entity and its relationships by id."""
        with self.db.tenant(self.config.namespace):
            result = await self.db.fetch_one(
                "DELETE FROM entities WHERE id = %s RETURNING id", (entity_id,)
            )
        return result is not None

    async def merge_entities(self, keep_id: int, merge_ids: list[int]) -> dict:
        """Merge one or more entities into a canonical one.

        Rewrites relationships and entity_chunks to point at `keep_id`,
        deduplicates any resulting duplicate edges, drops self-loops that
        the merge creates, then deletes the merged entities. All atomic.

        Raises ValueError if keep_id appears in merge_ids (would delete the
        canonical entity) or if merge_ids is empty.
        """
        if not merge_ids:
            raise ValueError("merge_ids must not be empty")
        if keep_id in merge_ids:
            raise ValueError(
                f"keep_id {keep_id} must not appear in merge_ids — "
                "that would delete the canonical entity"
            )

        with self.db.tenant(self.config.namespace):
            async with self.db.transaction() as tx:
                # Verify all entities exist and share a namespace. Cross-namespace
                # merges are almost always a bug.
                rows = await tx.fetch_all(
                    "SELECT id, namespace FROM entities WHERE id = ANY(%s)",
                    ([keep_id, *merge_ids],),
                )
                found_ids = {r["id"] for r in rows}
                missing = set([keep_id, *merge_ids]) - found_ids
                if missing:
                    raise ValueError(f"entities not found: {sorted(missing)}")
                namespaces = {r["namespace"] for r in rows}
                if len(namespaces) > 1:
                    raise ValueError(f"cross-namespace merge refused: {sorted(namespaces)}")

                # Repoint relationships. Migration 013 made
                # (namespace, src_id, dst_id, rel_type) uniquely indexed, so a
                # naive UPDATE that rewrites src_id or dst_id can collide with
                # an existing keep-anchored edge. Pre-delete the about-to-
                # collide rows so the UPDATE always lands. The semantics match
                # the prior post-UPDATE collapse (lowest-id wins) — we just
                # apply the dedup before the rewrite instead of after.
                #
                # src_id rewrite collision: a merge_id row (m, Y, rt) collides
                # if (keep_id, Y, rt) already exists.
                await tx.execute(
                    "DELETE FROM relationships m USING relationships k "
                    "WHERE m.src_id = ANY(%s) "
                    "  AND k.src_id = %s "
                    "  AND k.dst_id = m.dst_id "
                    "  AND k.rel_type = m.rel_type "
                    "  AND k.namespace = m.namespace "
                    "  AND k.id <> m.id",
                    (merge_ids, keep_id),
                )
                await tx.execute(
                    "UPDATE relationships SET src_id = %s WHERE src_id = ANY(%s)",
                    (keep_id, merge_ids),
                )
                # dst_id rewrite collision: a row (X, m, rt) collides if
                # (X, keep_id, rt) already exists. X may itself have just been
                # rewritten to keep_id — in that case the row becomes a
                # self-loop and the next DELETE handles it.
                await tx.execute(
                    "DELETE FROM relationships m USING relationships k "
                    "WHERE m.dst_id = ANY(%s) "
                    "  AND k.dst_id = %s "
                    "  AND k.src_id = m.src_id "
                    "  AND k.rel_type = m.rel_type "
                    "  AND k.namespace = m.namespace "
                    "  AND k.id <> m.id",
                    (merge_ids, keep_id),
                )
                await tx.execute(
                    "UPDATE relationships SET dst_id = %s WHERE dst_id = ANY(%s)",
                    (keep_id, merge_ids),
                )
                # Drop self-loops created by the merge.
                await tx.execute(
                    "DELETE FROM relationships WHERE src_id = dst_id AND "
                    "(src_id = %s OR dst_id = %s)",
                    (keep_id, keep_id),
                )

                # Copy entity_chunks rows from merged entities to keep_id,
                # deduping via ON CONFLICT, then delete the old rows.
                await tx.execute(
                    "INSERT INTO entity_chunks (entity_id, chunk_id, confidence, provenance) "
                    "SELECT %s, chunk_id, confidence, provenance FROM entity_chunks "
                    "WHERE entity_id = ANY(%s) "
                    "ON CONFLICT DO NOTHING",
                    (keep_id, merge_ids),
                )
                await tx.execute(
                    "DELETE FROM entity_chunks WHERE entity_id = ANY(%s)",
                    (merge_ids,),
                )

                # Delete merged entities.
                await tx.execute("DELETE FROM entities WHERE id = ANY(%s)", (merge_ids,))

        return {"kept": keep_id, "merged_count": len(merge_ids)}

    async def prune_orphans(self, namespace: str | None = None) -> dict:
        """Delete entities and relationships with no chunk links."""
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        with self.db.tenant(ns):
            # Count first, then delete — gives a clean int return value that's
            # easy to assert on in tests and log in production.
            ent_row = await self.db.fetch_one(
                "SELECT count(*) AS cnt FROM entities WHERE namespace = %s "
                "AND id NOT IN (SELECT DISTINCT entity_id FROM entity_chunks)",
                (ns,),
            )
            rel_row = await self.db.fetch_one(
                "SELECT count(*) AS cnt FROM relationships WHERE namespace = %s "
                "AND id NOT IN (SELECT DISTINCT relationship_id FROM relationship_chunks)",
                (ns,),
            )
            entities_pruned = ent_row["cnt"] if ent_row else 0
            relationships_pruned = rel_row["cnt"] if rel_row else 0
            await self.db.execute(
                "DELETE FROM entities WHERE namespace = %s AND id NOT IN "
                "(SELECT DISTINCT entity_id FROM entity_chunks)",
                (ns,),
            )
            await self.db.execute(
                "DELETE FROM relationships WHERE namespace = %s AND id NOT IN "
                "(SELECT DISTINCT relationship_id FROM relationship_chunks)",
                (ns,),
            )
        return {
            "entities_pruned": entities_pruned,
            "relationships_pruned": relationships_pruned,
        }

    async def tune_scoring_weights(self, **kwargs):
        """Grid-search scoring weights against a gold QA set.
        See src/pg_raggraph/evolution.py:tune_scoring_weights for args."""
        from pg_raggraph.evolution import tune_scoring_weights as _tune

        return await _tune(self, **kwargs)
