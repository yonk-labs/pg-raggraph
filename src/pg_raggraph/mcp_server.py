"""MCP server for pg-raggraph — exposes query/ingest/status as MCP tools.

Run with: `pgrg mcp-serve`

Implements the Model Context Protocol over stdio so any MCP client
(Claude Desktop, Cursor, Zed, etc.) can talk to a pg-raggraph instance.

Requires the `mcp` extra: `pip install pg-raggraph[mcp]`.
"""

from __future__ import annotations

import logging
import os
import traceback

from pg_raggraph import INGEST_ALLOWED_EXTS, GraphRAG

logger = logging.getLogger("pg_raggraph.mcp")


def _tool_error(tool_name: str, exc: Exception) -> dict:
    """Log full traceback locally; return sanitized error dict to the client.

    psycopg error messages often include the DSN, connection params, and SQL
    fragments. Never let them propagate to an MCP client (an untrusted agent).
    """
    logger.error("MCP tool %s failed:\n%s", tool_name, traceback.format_exc())
    return {"error": f"{tool_name} failed — check server logs for details."}


def _resolve_allowed_roots() -> list[str]:
    """Read PGRG_MCP_INGEST_ROOTS env var — colon-separated allowed roots.

    When empty or unset, MCP ingest is refused entirely. This is the safe
    default: an MCP client is an untrusted LLM agent that must not be able
    to ingest arbitrary filesystem paths and then query them back.
    """
    raw = os.environ.get("PGRG_MCP_INGEST_ROOTS", "").strip()
    if not raw:
        return []
    return [os.path.realpath(p) for p in raw.split(":") if p]


def _check_path_allowed(path: str, allowed_roots: list[str]) -> str:
    """Return canonical path if inside an allowed root, else raise.

    Resolves symlinks before checking so an attacker can't escape the
    sandbox with a symlink inside the allowed root.
    """
    canonical = os.path.realpath(path)
    for root in allowed_roots:
        # Require a proper path-component match so '/foo/bar' does not match
        # allowed root '/foo/ba'. Adding os.sep guards that.
        if canonical == root or canonical.startswith(root + os.sep):
            return canonical
    raise PermissionError(
        f"Path {path!r} is not inside an allowed MCP ingest root. "
        "Set PGRG_MCP_INGEST_ROOTS (colon-separated) to enable."
    )


def build_server(rag: GraphRAG):
    """Construct the MCP server with tools bound to a GraphRAG instance."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(
            "MCP server requires the 'mcp' package. Install with: pip install pg-raggraph[mcp]"
        ) from e

    server = FastMCP("pg-raggraph")

    @server.tool()
    async def pgrg_query(
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        profile: str | None = None,
    ) -> dict:
        """Query the knowledge base — returns chunks with sources and scores.

        mode: smart (default) | naive | naive_boost | local | global | hybrid
        """
        try:
            result = await rag.query(question, mode=mode, namespace=namespace, profile=profile)
            return {
                "query_mode": result.query_mode,
                "confidence": result.confidence,
                "top_score": result.top_score,
                "latency_ms": result.latency_ms,
                "chunks": [
                    {
                        "content": c.content,
                        "score": c.score,
                        "source": c.document_source,
                    }
                    for c in result.chunks
                ],
                "entities": [e.name for e in result.entities[:20]],
            }
        except Exception as exc:
            return _tool_error("pgrg_query", exc)

    @server.tool()
    async def pgrg_ask(
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        profile: str | None = None,
    ) -> dict:
        """Query + grounded LLM answer with citations.

        Falls back to a top-chunk summary if no LLM is configured.
        """
        try:
            result = await rag.ask(question, mode=mode, namespace=namespace, profile=profile)
            return {
                "answer": result.answer,
                "confidence": result.confidence,
                "sources": [c.document_source for c in result.chunks[:5] if c.document_source],
                "latency_ms": result.latency_ms,
            }
        except Exception as exc:
            return _tool_error("pgrg_ask", exc)

    @server.tool()
    async def pgrg_profiles() -> dict:
        """Return retrieval profile ladder metadata and calibration estimates."""
        try:
            return rag.profiles()
        except Exception as exc:
            return _tool_error("pgrg_profiles", exc)

    @server.tool()
    async def pgrg_get_namespace_profile(namespace: str | None = None) -> dict:
        """Return the persisted retrieval profile default for a namespace."""
        try:
            return await rag.get_namespace_profile(namespace)
        except Exception as exc:
            return _tool_error("pgrg_get_namespace_profile", exc)

    @server.tool()
    async def pgrg_set_namespace_profile(namespace: str, profile: str) -> dict:
        """Persist a namespace retrieval profile default."""
        try:
            return await rag.set_namespace_profile(namespace, profile)
        except Exception as exc:
            return _tool_error("pgrg_set_namespace_profile", exc)

    allowed_roots = _resolve_allowed_roots()

    @server.tool()
    async def pgrg_ingest(paths: list[str], namespace: str | None = None) -> dict:
        """Ingest files or directories into the knowledge base.

        Paths must be inside a root listed in PGRG_MCP_INGEST_ROOTS
        (colon-separated). If that env var is unset, ingestion is refused —
        an MCP client is untrusted and must not be able to pull in
        arbitrary filesystem paths (/etc, ~/.ssh, etc.) and query them back.

        File paths must have an allowed extension (see INGEST_ALLOWED_EXTS).
        Directory paths are walked by the library and filtered there, so a
        directory containing both .md and .exe will only ingest the .md
        files. PR-304: an explicit file path with a non-allowed extension is
        rejected here so an LLM agent can't ingest binaries by listing them.
        """
        if not allowed_roots:
            return {
                "error": "MCP ingest is disabled. Set PGRG_MCP_INGEST_ROOTS "
                "(colon-separated absolute paths) to enable it."
            }
        try:
            safe_paths = [_check_path_allowed(p, allowed_roots) for p in paths]
            rejected = []
            for p in safe_paths:
                if os.path.isfile(p):
                    ext = os.path.splitext(p)[1].lower()
                    if ext not in INGEST_ALLOWED_EXTS:
                        rejected.append(
                            {
                                "path": p,
                                "error": "unsupported_extension",
                                "ext": ext,
                            }
                        )
            if rejected:
                return {
                    "error": "unsupported_extension",
                    "rejected": rejected,
                    "allowed": list(INGEST_ALLOWED_EXTS),
                }
            await rag.ingest(safe_paths, namespace=namespace)
            return await rag.status(namespace=namespace)
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return _tool_error("pgrg_ingest", exc)

    @server.tool()
    async def pgrg_status(namespace: str | None = None) -> dict:
        """Return counts of documents, chunks, entities, and relationships."""
        try:
            return await rag.status(namespace=namespace)
        except Exception as exc:
            return _tool_error("pgrg_status", exc)

    @server.tool()
    async def pgrg_delete_document(
        source_path: str, namespace: str | None = None, confirm: bool = False
    ) -> dict:
        """Delete a document by source path.

        Requires confirm=True as a guard against accidental deletion by agents.
        """
        if not confirm:
            return {
                "error": "Deletion refused. Pass confirm=True to acknowledge this "
                "is intentional and not an agent hallucination."
            }
        try:
            count = await rag.delete_document(source_path, namespace=namespace)
            return {"deleted": count}
        except Exception as exc:
            return _tool_error("pgrg_delete_document", exc)

    return server


async def run_stdio(**config_kwargs) -> None:
    """Run the MCP server over stdio."""
    rag = GraphRAG(**config_kwargs)
    await rag.connect()
    try:
        server = build_server(rag)
        await server.run_stdio_async()
    finally:
        await rag.close()
