"""MCP response helpers — staleness banner + footer (PG-3).

The banner surfaces documents whose entity/relationship graph is mid-
extraction (graph_status='pending' or 'processing') so the agent knows
to fall back to direct file reads for them. Chunks themselves are always
fresh; only the LLM/lede-extracted graph layer lags.

The chokepoint (_apply_freshness in this module) is called by every MCP
tool's response builder in mcp_server.py. Tools that don't reference
documents still call it — no-ops when nothing is pending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class PendingDocument:
    """A document mid-extraction whose entity/relationship graph may be stale."""

    namespace: str
    document_id: str
    source_path: str | None  # file path if known; None for non-file ingests
    created_at: datetime  # documents.created_at — used for age display
    graph_status: str  # 'pending' | 'processing'


def _format_age(age_seconds: int) -> str:
    """SC-006: <60s → 'Ns ago', <3600s → 'Nm ago', ≥3600s → 'Nh ago'."""
    if age_seconds < 60:
        return f"{age_seconds}s ago"
    if age_seconds < 3600:
        return f"{age_seconds // 60}m ago"
    return f"{age_seconds // 3600}h ago"


def _label(status: str) -> str:
    return "extraction in progress" if status == "processing" else "pending extraction"


def _location(doc: PendingDocument) -> str:
    if doc.source_path:
        return doc.source_path
    return f"{doc.namespace}:{doc.document_id}"


def format_stale_banner(
    pending: Iterable[PendingDocument],
    *,
    now: datetime | None = None,
) -> str:
    """Prefix banner for MCP responses that cite mid-extraction documents.

    Empty iterable ⇒ empty string (SC-005). Otherwise: starts with ⚠️,
    lists each document by source_path (or namespace:document_id), with
    its age and lifecycle label, then a closing instruction to Read
    those documents directly for live content. The chunks themselves
    and any non-cited part of the response remain authoritative.
    """
    pending = list(pending)
    if not pending:
        return ""
    if now is None:
        now = datetime.now(timezone.utc)
    lines = []
    for doc in pending:
        age = int((now - doc.created_at).total_seconds())
        lines.append(
            f"  - {_location(doc)} (ingested {_format_age(age)}, {_label(doc.graph_status)})"
        )
    body = "\n".join(lines)
    return (
        "⚠️ Some cited documents are still being processed by the entity-"
        "extraction background job — their entity/relationship graph "
        "entries may be stale:\n"
        + body
        + "\nFor authoritative content of those specific documents, Read them "
        "directly. The chunks themselves and the rest of this response are fresh."
    )


def format_stale_footer(
    pending: Iterable[PendingDocument],
    *,
    now: datetime | None = None,
    max_shown: int = 5,
) -> str:
    """Compact footer listing pending documents NOT cited in this response.

    Gives the agent a project-wide freshness picture without bloating
    the main banner. Caps at max_shown (default 5) with a '... and N
    more' suffix. Empty iterable ⇒ empty string (SC-005).
    """
    pending = list(pending)
    if not pending:
        return ""
    if now is None:
        now = datetime.now(timezone.utc)
    shown = pending[:max_shown]
    extra = len(pending) - len(shown)
    lines = [f"  - {_location(doc)}" for doc in shown]
    suffix = f"\n  ... and {extra} more" if extra > 0 else ""
    return (
        "---\nNamespace freshness — other pending documents not cited above:\n"
        + "\n".join(lines)
        + suffix
    )


async def _apply_freshness(
    response: dict,
    *,
    rag,  # pg_raggraph.GraphRAG — no annotation to avoid circular import
    namespace: str | None,
) -> dict:
    """Inject `banner` and `footer` keys into an MCP tool's response dict
    when documents in the namespace are mid-extraction.

    Contract:
      * namespace is None ⇒ no-op (returns the original response unchanged).
        Some tools (pgrg_profiles, pgrg_get_namespace_profile with no arg)
        don't operate on a single namespace; nothing to compute.
      * No pending docs in the namespace ⇒ no-op (SC-005). The response
        shape is byte-for-byte identical to v0.5.0a1.
      * Pending docs exist ⇒ adds:
          - `banner` (str) when at least one cited document is pending,
            naming each one (SC-003).
          - `footer` (str) when at least one non-cited document is pending,
            listing up to 5 with '... and N more' overflow (SC-004).

    "Cited" is determined from the response's `chunks` (pgrg_query) or
    `sources` (pgrg_ask) keys. Tools that return neither (pgrg_status,
    pgrg_profiles, …) treat every pending doc as "non-cited" and surface
    them through `footer` only — that's still useful freshness signal.
    """
    if namespace is None:
        return response

    pending = await rag.db.list_pending_documents(namespace)
    if not pending:
        return response

    cited_sources = _cited_sources_from_response(response)

    cited = [p for p in pending if p.source_path in cited_sources]
    non_cited = [p for p in pending if p.source_path not in cited_sources]

    banner = format_stale_banner(cited)
    footer = format_stale_footer(non_cited)

    if banner:
        response["banner"] = banner
    if footer:
        response["footer"] = footer
    return response


def _cited_sources_from_response(response: dict) -> set[str]:
    """Extract source_path strings cited in a tool's response.

    pgrg_query returns `chunks: [{source: str, ...}]`; pgrg_ask returns
    `sources: list[str]`. Other tools (pgrg_status) reuse the keys for
    scalar counts (e.g. `chunks: 1`) — guard against that and treat
    non-list values as "no cited sources" so the chokepoint falls back
    to surfacing everything via the footer.
    """
    cited: set[str] = set()
    chunks = response.get("chunks")
    if isinstance(chunks, list):
        for chunk in chunks:
            src = chunk.get("source") if isinstance(chunk, dict) else None
            if src:
                cited.add(src)
    sources = response.get("sources")
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, str):
                cited.add(src)
    return cited
