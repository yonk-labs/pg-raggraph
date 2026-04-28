"""FastAPI server for pg-raggraph."""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig

try:
    from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as e:
    raise ImportError("Install server extras: pip install pg-raggraph[server]") from e


_logger = logging.getLogger("pg_raggraph.server")

STATIC_DIR = Path(__file__).parent / "static"

# PR-104: extension allowlist for /ingest. Mirrors SUPPORTED_EXTS in
# pg_raggraph.__init__.ingest so the server only accepts what the ingest
# pipeline can actually consume.
_INGEST_ALLOWED_EXTS = frozenset(
    {".md", ".txt", ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".rst"}
)
_DEFAULT_MAX_UPLOAD_MB = 100
# PR-104: filename sanitization. Strip any character outside [A-Za-z0-9._-]
# and collapse runs of underscores. Path components are stripped via
# os.path.basename before this regex runs.
_FILENAME_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9._-]")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _sanitize_filename(name: str) -> str | None:
    """Allowlist-based filename sanitization.

    Returns the cleaned base name, or None if nothing acceptable remains.
    Path separators are stripped via basename() first; remaining disallowed
    chars become '_', repeated underscores collapse, leading/trailing
    '_' or '.' are stripped to avoid hidden-file or empty-name edge cases.
    """
    if not name:
        return None
    base = os.path.basename(name)
    if not base:
        return None
    cleaned = _FILENAME_DISALLOWED_RE.sub("_", base)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_.")
    return cleaned or None


def create_app(**kwargs) -> FastAPI:
    """Create the FastAPI application."""
    config = PGRGConfig(**kwargs)
    rag = GraphRAG(**kwargs)

    # PR-104: optional Bearer-token auth. When PGRG_SERVER_API_KEY is unset
    # the server runs unauthenticated and logs a startup WARN — we want the
    # missing-auth state to be loud, not silent.
    api_key = os.environ.get("PGRG_SERVER_API_KEY", "").strip()
    if not api_key:
        _logger.warning(
            "pgrg server starting without PGRG_SERVER_API_KEY — running with "
            "NO authentication. Do not expose this server to untrusted networks."
        )

    # PR-205: Origin allowlist for state-changing methods. When
    # PGRG_SERVER_ALLOWED_ORIGINS is unset, only loopback Origin is accepted
    # on POST/PUT/DELETE/PATCH (or no Origin header at all — non-browser
    # clients still work). When set, only listed origins are accepted.
    allowed_origins_env = os.environ.get("PGRG_SERVER_ALLOWED_ORIGINS", "").strip()
    allowed_origins = (
        [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
        if allowed_origins_env
        else []
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await rag.connect()
        yield
        await rag.close()

    from pg_raggraph import __version__

    app = FastAPI(
        title="pg-raggraph",
        description="PostgreSQL-native GraphRAG API",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def _auth_and_origin_middleware(request: Request, call_next):
        path = request.url.path
        # Probes never need auth — k8s shouldn't have to ship a bearer.
        is_probe = path in ("/health", "/ready")

        if api_key and not is_probe:
            bearer = request.headers.get("Authorization", "")
            if not bearer.startswith("Bearer "):
                return JSONResponse({"detail": "missing Bearer token"}, status_code=401)
            if bearer[len("Bearer ") :].strip() != api_key:
                return JSONResponse({"detail": "invalid API key"}, status_code=401)

        # Origin check on state-changing methods. Browsers always send Origin
        # on cross-origin POST; same-origin POST omits it. Non-browser
        # clients (curl, requests, httpx) typically don't send Origin and
        # are unaffected.
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("Origin", "")
            if origin:
                if allowed_origins:
                    if origin not in allowed_origins:
                        return JSONResponse(
                            {"detail": f"origin {origin!r} not in allowlist"},
                            status_code=403,
                        )
                else:
                    host = (urlparse(origin).hostname or "").lower()
                    if host not in _LOOPBACK_HOSTS:
                        return JSONResponse(
                            {
                                "detail": (
                                    f"origin {origin!r} not allowed without "
                                    "PGRG_SERVER_ALLOWED_ORIGINS set"
                                )
                            },
                            status_code=403,
                        )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the web UI."""
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
        return HTMLResponse("<h1>pg-raggraph</h1><p>Web UI not found.</p>")

    @app.get("/health")
    async def health():
        """Liveness probe — is the process up and the DB reachable?

        Cheap. Suitable for high-frequency liveness checks. Use /ready for
        a stronger "fully initialized and safe to serve traffic" signal.
        """
        db_ok = await rag.db.health_check()
        if not db_ok:
            from fastapi.responses import JSONResponse

            return JSONResponse({"status": "unhealthy", "db": "unreachable"}, status_code=503)
        return {"status": "ok", "db": "connected"}

    @app.get("/ready")
    async def ready():
        """Readiness probe — DB up AND schema at the version this build expects.

        Returns 503 with a structured payload when migrations are pending or
        the schema_version meta row is missing. Distinct from /health so
        rolling deployments don't route traffic to a pod whose DB is up but
        whose migrations haven't been applied yet.
        """
        from fastapi.responses import JSONResponse

        from pg_raggraph.db import SCHEMA_VERSION

        db_ok = await rag.db.health_check()
        if not db_ok:
            return JSONResponse({"status": "unready", "reason": "db_unreachable"}, status_code=503)
        try:
            applied = int(await rag.db.get_meta("schema_version") or 0)
        except Exception as e:
            return JSONResponse(
                {"status": "unready", "reason": "schema_meta_error", "detail": str(e)},
                status_code=503,
            )
        if applied < SCHEMA_VERSION:
            return JSONResponse(
                {
                    "status": "unready",
                    "reason": "schema_pending_migration",
                    "current": applied,
                    "expected": SCHEMA_VERSION,
                },
                status_code=503,
            )
        return {
            "status": "ready",
            "db": "connected",
            "schema_version": applied,
            "expected_schema_version": SCHEMA_VERSION,
        }

    @app.get("/status")
    async def status(namespace: str | None = None):
        return await rag.status(namespace)

    @app.post("/query")
    async def query(
        question: str = Form(...),
        # PR-202: default `smart` matches /ask. `hybrid` was historically the
        # slowest mode (~3 s vs ~80 ms for naive_boost) — wrong default for a
        # public endpoint. See benchmarks/age-bakeoff/results/REPORT-VERDICT.md.
        mode: str = Form("smart"),
        namespace: str = Form(None),
    ):
        result = await rag.query(question, mode=mode, namespace=namespace)
        return result.model_dump()

    @app.post("/ask")
    async def ask(
        question: str = Form(...),
        mode: str = Form("smart"),
        namespace: str = Form(None),
    ):
        """Query + grounded LLM answer. Falls back to top-chunk summary without LLM.

        Each returned chunk's `content` is truncated to
        `PGRG_SERVER_ASK_CHUNK_PREVIEW_CHARS` characters (default 500) so the
        response stays bounded even on long-document corpora. Set the env to
        `0` to disable truncation, or any positive integer to widen the window.
        """
        preview_chars = int(os.environ.get("PGRG_SERVER_ASK_CHUNK_PREVIEW_CHARS", "500"))
        result = await rag.ask(question, mode=mode, namespace=namespace)
        return {
            "answer": result.answer,
            "confidence": result.confidence,
            "latency_ms": result.latency_ms,
            "query_mode": result.query_mode,
            "chunks": [
                {
                    "content": c.content if preview_chars <= 0 else c.content[:preview_chars],
                    "score": c.score,
                    "source": c.document_source,
                }
                for c in result.chunks[:5]
            ],
            "entities": [e.name for e in result.entities[:10]],
        }

    @app.get("/graph")
    async def graph(
        namespace: str | None = None,
        # PR-103: bound the response. Default 500 nodes / 500 edges keeps
        # vis-network responsive even on big namespaces. `?limit=all` is
        # the documented OOM footgun for tiny corpora that want everything.
        # Cap explicit numeric values at 5000 so a malicious caller can't
        # pass `?limit=999999999` and OOM the browser anyway.
        limit: str | None = Query(
            default=None,
            description=(
                "Max nodes/edges returned. Default 500. Pass an integer up to "
                "5000, or 'all' to return everything (use only on small corpora "
                "— this is the OOM footgun)."
            ),
        ),
    ):
        """Return entity/relationship data for visualization (paginated).

        On a 909-doc corpus an unbounded /graph returns ~17K nodes + ~38K
        edges, which makes vis-network choke on the browser side. The default
        cap of 500 keeps the demo UI usable; pass `?limit=N` (max 5000) to
        widen the window or `?limit=all` if you really want everything.
        """
        ns = namespace or config.namespace

        # Resolve `limit` to either an int row-cap or None (= unbounded).
        if limit is None:
            row_cap: int | None = 500
        elif limit == "all":
            row_cap = None
        else:
            try:
                row_cap = int(limit)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=(f"Invalid limit={limit!r}. Pass an integer (max 5000) or 'all'."),
                ) from e
            if row_cap < 1:
                raise HTTPException(status_code=400, detail="limit must be >= 1.")
            if row_cap > 5000:
                raise HTTPException(
                    status_code=400,
                    detail="limit max is 5000. Use `?limit=all` if you really need more.",
                )

        ent_sql = (
            "SELECT id, name, entity_type, description "
            "FROM entities WHERE namespace = %s ORDER BY id"
        )
        rel_sql = (
            "SELECT r.id, e1.name as source, e2.name as target, r.rel_type, "
            "r.description FROM relationships r "
            "JOIN entities e1 ON e1.id = r.src_id "
            "JOIN entities e2 ON e2.id = r.dst_id "
            "WHERE r.namespace = %s ORDER BY r.id"
        )
        if row_cap is not None:
            ent_sql += " LIMIT %s"
            rel_sql += " LIMIT %s"
            ent_params: tuple = (ns, row_cap)
            rel_params: tuple = (ns, row_cap)
        else:
            ent_params = (ns,)
            rel_params = (ns,)

        entities = await rag.db.fetch_all(ent_sql, ent_params)
        relationships = await rag.db.fetch_all(rel_sql, rel_params)
        nodes = [{"id": e["id"], "label": e["name"], "group": e["entity_type"]} for e in entities]
        edges = [
            {
                "from": r["source"],
                "to": r["target"],
                "label": r["rel_type"],
                "title": r["description"],
            }
            for r in relationships
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "limit": "all" if row_cap is None else row_cap,
            "truncated": row_cap is not None and (len(nodes) >= row_cap or len(edges) >= row_cap),
        }

    @app.post("/ingest")
    async def ingest(
        files: list[UploadFile] = File(...),
        namespace: str = Form(None),
    ):
        """Upload and ingest files.

        PR-104 hardening:
          * 413 if any file exceeds PGRG_SERVER_MAX_UPLOAD_MB (default 100).
          * 415 if any extension is outside the ingest allowlist.
          * 400 if a filename sanitizes to nothing usable.
          * Temp-file cleanup is always run via try/finally — leak-proof
            even if rag.ingest() raises mid-batch.
        """
        import tempfile

        max_upload_mb = int(os.environ.get("PGRG_SERVER_MAX_UPLOAD_MB", _DEFAULT_MAX_UPLOAD_MB))
        max_bytes = max_upload_mb * 1024 * 1024
        ns = namespace or config.namespace

        # Pre-validate every file before writing anything to /tmp. Cheap to
        # reject early; we keep the temp-write loop simple.
        validated: list[tuple[UploadFile, str]] = []  # (file, sanitized_name)
        for f in files:
            ext = os.path.splitext(f.filename or "")[1].lower()
            if ext not in _INGEST_ALLOWED_EXTS:
                raise HTTPException(
                    status_code=415,
                    detail=(
                        f"file extension {ext or '(none)'} not allowed. "
                        f"Allowed: {sorted(_INGEST_ALLOWED_EXTS)}"
                    ),
                )
            # `f.size` is set by Starlette/FastAPI 0.110+ for multipart
            # uploads. None means we'll have to size-check after read.
            if f.size is not None and f.size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"upload {f.filename!r} is {f.size} bytes; "
                        f"max is {max_bytes} ({max_upload_mb} MB). "
                        "Set PGRG_SERVER_MAX_UPLOAD_MB to override."
                    ),
                )
            sanitized = _sanitize_filename(f.filename or "")
            if not sanitized:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"filename {f.filename!r} is empty after sanitization "
                        "(allowed chars: A-Za-z0-9._-; path separators stripped)."
                    ),
                )
            validated.append((f, sanitized))

        paths: list[str] = []
        try:
            for f, sanitized in validated:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{sanitized}")
                try:
                    content = await f.read()
                    if len(content) > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"upload {f.filename!r} exceeds {max_upload_mb} MB "
                                "after read. Set PGRG_SERVER_MAX_UPLOAD_MB to override."
                            ),
                        )
                    tmp.write(content)
                finally:
                    tmp.close()
                paths.append(tmp.name)

            await rag.ingest(paths, namespace=ns)

            status = await rag.status(ns)
            return {
                "status": "ok",
                "namespace": ns,
                "documents": status["documents"],
                "entities": status["entities"],
                "relationships": status["relationships"],
            }
        finally:
            # Always clean up temp files — even if ingest() raised mid-batch
            # (PR-104: prior code only cleaned on the success path).
            for p in paths:
                try:
                    os.unlink(p)
                except OSError as e:
                    _logger.debug("Temp cleanup failed for %s: %s", p, e)

    return app
