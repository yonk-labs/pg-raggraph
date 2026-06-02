"""Unit tests for the MCP staleness banner / footer (SC-003..SC-006)."""

from datetime import datetime, timedelta, timezone

import pytest

from pg_raggraph.mcp_helpers import (
    PendingDocument,
    format_stale_banner,
    format_stale_footer,
)

FIXED_NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _doc(seconds_old: int, *, source_path: str = "/repo/docs/spec.md", status: str = "pending"):
    return PendingDocument(
        namespace="crm",
        document_id=str(seconds_old),
        source_path=source_path,
        created_at=FIXED_NOW - timedelta(seconds=seconds_old),
        graph_status=status,
    )


def test_empty_pending_returns_empty_string():
    """SC-005: zero pending docs ⇒ banner and footer both empty."""
    assert format_stale_banner([], now=FIXED_NOW) == ""
    assert format_stale_footer([], now=FIXED_NOW) == ""


def test_banner_emoji_and_closing_phrase():
    """SC-003: banner starts with ⚠️ and ends with the read-directly instruction."""
    banner = format_stale_banner([_doc(30)], now=FIXED_NOW)
    assert banner.startswith("⚠️")
    assert "Read them directly" in banner


def test_banner_lists_source_path():
    """SC-003: banner names the document by source_path when present."""
    banner = format_stale_banner([_doc(30, source_path="/repo/docs/auth.md")], now=FIXED_NOW)
    assert "/repo/docs/auth.md" in banner


def test_banner_falls_back_to_namespace_id_when_no_source_path():
    """SC-003: when source_path is None, fall back to namespace:document_id."""
    doc = PendingDocument(
        namespace="crm",
        document_id="42",
        source_path=None,
        created_at=FIXED_NOW - timedelta(seconds=30),
        graph_status="pending",
    )
    banner = format_stale_banner([doc], now=FIXED_NOW)
    assert "crm:42" in banner


@pytest.mark.parametrize(
    "seconds_old,expected_token",
    [
        (30, "30s ago"),  # SC-006: <60s
        (90, "1m ago"),  # SC-006: <3600s, integer-minute boundary
        (60 * 65, "1h ago"),  # SC-006: ≥3600s, integer-hour boundary
        (60 * 60 * 4, "4h ago"),
    ],
)
def test_age_formatting_boundaries(seconds_old, expected_token):
    """SC-006: age formatting flips s → m → h at 60 and 3600 second boundaries."""
    banner = format_stale_banner([_doc(seconds_old)], now=FIXED_NOW)
    assert expected_token in banner, f"expected {expected_token!r} for {seconds_old}s old"


def test_banner_labels_processing_distinctly_from_pending():
    """A 'processing' doc is labeled in flight; 'pending' is queued."""
    pending = format_stale_banner([_doc(30, status="pending")], now=FIXED_NOW)
    processing = format_stale_banner([_doc(30, status="processing")], now=FIXED_NOW)
    assert "pending extraction" in pending
    assert "extraction in progress" in processing


def test_footer_caps_at_5_and_overflows():
    """SC-004: footer lists up to 5 docs, then '+N more'."""
    docs = [_doc(i * 10, source_path=f"/repo/n{i}.md") for i in range(8)]
    footer = format_stale_footer(docs, now=FIXED_NOW, max_shown=5)
    assert "/repo/n0.md" in footer
    assert "/repo/n4.md" in footer
    assert "/repo/n5.md" not in footer  # over the cap
    assert "and 3 more" in footer


def test_footer_under_cap_has_no_overflow_suffix():
    """If pending fits under max_shown, no '+N more' line."""
    docs = [_doc(i * 10, source_path=f"/repo/n{i}.md") for i in range(3)]
    footer = format_stale_footer(docs, now=FIXED_NOW, max_shown=5)
    assert "and " not in footer or "more" not in footer
