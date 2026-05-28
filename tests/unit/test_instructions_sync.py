"""Drift guard for the SERVER_INSTRUCTIONS / user-guide / README triad (SC-007).

If this test fails, you updated one of the three surfaces and forgot the
others. Edit all three together — see CLAUDE.md "House Rules".
"""

from pathlib import Path

from pg_raggraph.server_instructions import SERVER_INSTRUCTIONS  # noqa: F401

REPO = Path(__file__).resolve().parents[2]

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


def test_user_guide_mentions_each_mcp_tool():
    user_guide = (REPO / "docs/user-guide.md").read_text()
    missing = [t for t in CURRENT_MCP_TOOLS if t not in user_guide]
    assert not missing, (
        f"docs/user-guide.md is missing MCP tool name(s) listed in "
        f"SERVER_INSTRUCTIONS: {missing}. Update the MCP server section "
        f"to match the playbook."
    )


def test_readme_mentions_pgrg_mcp_serve():
    readme = (REPO / "README.md").read_text()
    assert "pgrg mcp-serve" in readme or "pgrg mcp serve" in readme, (
        "README.md must mention 'pgrg mcp-serve' so users discover the MCP "
        "server before reading the user-guide."
    )


def test_claude_md_has_three_files_sync_house_rule():
    claude_md = (REPO / "CLAUDE.md").read_text()
    assert "server_instructions.py" in claude_md, (
        "CLAUDE.md must document the three-files-stay-in-sync House Rule "
        "naming server_instructions.py, user-guide.md, and README.md."
    )


def test_playbook_emoji_present_in_user_guide():
    """The playbook's anti-pattern about the ⚠️ banner should appear in
    the user-guide too — otherwise users reading docs without seeing
    the MCP initialize response will miss the freshness model."""
    user_guide = (REPO / "docs/user-guide.md").read_text()
    assert "⚠️" in user_guide, (
        "user-guide MCP section should reference the ⚠️ staleness banner "
        "(SERVER_INSTRUCTIONS does)."
    )
