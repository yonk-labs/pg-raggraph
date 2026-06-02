"""Unit tests for the MCP initialize playbook (PG-1 / SC-001)."""

from pg_raggraph.server_instructions import SERVER_INSTRUCTIONS

REQUIRED_SECTIONS = (
    "Answer directly",
    "Tool selection by intent",
    "Common chains",
    "Anti-patterns",
    "Limitations",
)

# The 8 MCP tools currently registered in mcp_server.py:build_server.
# Update this list if and only if the tool registry changes (then update
# the playbook too — that's the whole point of SC-007's sync test).
CURRENT_MCP_TOOLS = (
    "pgrg_query",
    "pgrg_ask",
    "pgrg_profiles",
    "pgrg_get_namespace_profile",
    "pgrg_set_namespace_profile",
    "pgrg_ingest",
    "pgrg_status",
    "pgrg_delete_document",
)


def test_playbook_has_required_sections():
    for section in REQUIRED_SECTIONS:
        assert section in SERVER_INSTRUCTIONS, f"playbook missing section: {section!r}"


def test_playbook_lists_all_8_mcp_tools():
    for tool in CURRENT_MCP_TOOLS:
        assert tool in SERVER_INSTRUCTIONS, f"playbook does not mention tool {tool!r}"


def test_playbook_does_not_reference_pgrg_code_impact():
    # Out-of-scope per the mission brief. If someone adds the MCP tool
    # later (Option B), they'll need to remove this guard intentionally
    # rather than drift the playbook unilaterally.
    assert "pgrg_code_impact" not in SERVER_INSTRUCTIONS, (
        "pgrg_code_impact is NOT an MCP tool today; do not reference it"
    )


def test_playbook_mentions_staleness_banner_concept():
    # PG-1's playbook references the PG-3 banner under "Anti-patterns".
    # The exact emoji/phrase below is verbatim from the playbook —
    # the sync expectation is what keeps PG-1 + PG-3 from drifting.
    assert "⚠️" in SERVER_INSTRUCTIONS
    assert "staleness banner" in SERVER_INSTRUCTIONS.lower()


def test_playbook_mentions_background_extraction():
    # Background extraction (defer_extraction=True) is the v0.5.0a1
    # feature that makes the banner meaningful in the first place.
    assert "defer_extraction" in SERVER_INSTRUCTIONS
