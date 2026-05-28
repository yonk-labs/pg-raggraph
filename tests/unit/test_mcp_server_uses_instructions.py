"""Unit test: build_server attaches SERVER_INSTRUCTIONS to FastMCP (SC-002)."""

from unittest.mock import MagicMock

import pytest

mcp = pytest.importorskip("mcp.server.fastmcp", reason="mcp not installed")

from pg_raggraph.mcp_server import build_server  # noqa: E402
from pg_raggraph.server_instructions import SERVER_INSTRUCTIONS  # noqa: E402


def test_build_server_passes_instructions_to_fastmcp():
    """SC-002: FastMCP receives SERVER_INSTRUCTIONS via instructions=."""
    # build_server doesn't actually need a connected rag for this assertion —
    # it only reads .config / .db lazily inside tool bodies. A bare mock is
    # fine to confirm the constructor argument flows through.
    rag = MagicMock()
    server = build_server(rag)
    assert server.instructions == SERVER_INSTRUCTIONS, (
        "FastMCP must receive SERVER_INSTRUCTIONS via the instructions= kwarg"
    )
