"""FastAPI server for pg-raggraph."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig

try:
    from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
    from fastapi.responses import HTMLResponse
except ImportError as e:
    raise ImportError("Install server extras: pip install pg-raggraph[server]") from e


STATIC_DIR = Path(__file__).parent / "static"


def create_app(**kwargs) -> FastAPI:
    """Create the FastAPI application."""
    config = PGRGConfig(**kwargs)
    rag = GraphRAG(**kwargs)

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
            return JSONResponse(
                {"status": "unready", "reason": "db_unreachable"}, status_code=503
            )
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
        """Query + grounded LLM answer. Falls back to top-chunk summary without LLM."""
        result = await rag.ask(question, mode=mode, namespace=namespace)
        return {
            "answer": result.answer,
            "confidence": result.confidence,
            "latency_ms": result.latency_ms,
            "query_mode": result.query_mode,
            "chunks": [
                {
                    "content": c.content[:500],
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
                    detail=(
                        f"Invalid limit={limit!r}. Pass an integer (max 5000) "
                        "or 'all'."
                    ),
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
            "truncated": row_cap is not None and (
                len(nodes) >= row_cap or len(edges) >= row_cap
            ),
        }

    @app.post("/ingest")
    async def ingest(
        files: list[UploadFile] = File(...),
        namespace: str = Form(None),
    ):
        """Upload and ingest files."""
        import tempfile

        ns = namespace or config.namespace
        paths = []
        for f in files:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{f.filename}")
            content = await f.read()
            tmp.write(content)
            tmp.close()
            paths.append(tmp.name)

        await rag.ingest(paths, namespace=ns)

        # Clean up temp files
        for p in paths:
            os.unlink(p)

        status = await rag.status(ns)
        return {
            "status": "ok",
            "namespace": ns,
            "documents": status["documents"],
            "entities": status["entities"],
            "relationships": status["relationships"],
        }

    return app
