"""FastAPI server for pg-raggraph."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig

try:
    from fastapi import FastAPI, File, Form, UploadFile
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

    app = FastAPI(
        title="pg-raggraph",
        description="PostgreSQL-native GraphRAG API",
        version="0.1.0",
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
        db_ok = await rag.db.health_check()
        if not db_ok:
            from fastapi.responses import JSONResponse

            return JSONResponse({"status": "unhealthy", "db": "unreachable"}, status_code=503)
        return {"status": "ok", "db": "connected"}

    @app.get("/status")
    async def status(namespace: str | None = None):
        return await rag.status(namespace)

    @app.post("/query")
    async def query(
        question: str = Form(...),
        mode: str = Form("hybrid"),
        namespace: str = Form(None),
    ):
        result = await rag.query(question, mode=mode, namespace=namespace)
        return result.model_dump()

    @app.get("/graph")
    async def graph(namespace: str | None = None):
        """Return entity/relationship data for visualization."""
        ns = namespace or config.namespace
        entities = await rag.db.fetch_all(
            "SELECT id, name, entity_type, description FROM entities WHERE namespace = %s",
            (ns,),
        )
        relationships = await rag.db.fetch_all(
            "SELECT r.id, e1.name as source, e2.name as target, r.rel_type, r.description "
            "FROM relationships r "
            "JOIN entities e1 ON e1.id = r.src_id "
            "JOIN entities e2 ON e2.id = r.dst_id "
            "WHERE r.namespace = %s",
            (ns,),
        )
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
        return {"nodes": nodes, "edges": edges}

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
