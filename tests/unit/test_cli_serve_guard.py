"""PR-217 — `pgrg serve`/`pgrg demo` bind guard.

The serve default moved from 0.0.0.0 to 127.0.0.1, and a non-loopback
bind is REFUSED unless PGRG_SERVER_API_KEY is set (or the operator
explicitly passes --insecure-no-auth). No real socket is ever bound:
uvicorn.run is monkeypatched to capture its arguments.
"""

from __future__ import annotations

import uvicorn
from click.testing import CliRunner

from pg_raggraph.cli import main


def _invoke_serve(monkeypatch, args, *, api_key: str | None = None):
    """Run `pgrg serve` with uvicorn.run captured. Returns (result, calls)."""
    calls: list[dict] = []

    def fake_run(app, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    if api_key is None:
        monkeypatch.delenv("PGRG_SERVER_API_KEY", raising=False)
    else:
        monkeypatch.setenv("PGRG_SERVER_API_KEY", api_key)
    result = CliRunner().invoke(main, args)
    return result, calls


def test_serve_default_binds_loopback(monkeypatch):
    """No flags → 127.0.0.1, even with no API key configured."""
    result, calls = _invoke_serve(monkeypatch, ["serve"])
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8080


def test_serve_nonloopback_without_key_refused(monkeypatch):
    """0.0.0.0 with no key → exit non-zero, message names the env var
    and the override flag, and uvicorn is never started."""
    result, calls = _invoke_serve(monkeypatch, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert not calls, "uvicorn.run must not be called on refusal"
    assert "PGRG_SERVER_API_KEY" in result.stderr
    assert "--insecure-no-auth" in result.stderr


def test_serve_nonloopback_with_key_starts(monkeypatch):
    result, calls = _invoke_serve(
        monkeypatch, ["serve", "--host", "0.0.0.0"], api_key="test-key-123"
    )
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["host"] == "0.0.0.0"


def test_serve_insecure_flag_overrides_with_loud_warning(monkeypatch):
    result, calls = _invoke_serve(
        monkeypatch, ["serve", "--host", "0.0.0.0", "--insecure-no-auth"]
    )
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["host"] == "0.0.0.0"
    assert "UNAUTHENTICATED" in result.stderr


def test_serve_localhost_and_ipv6_loopback_allowed(monkeypatch):
    """The named loopbacks pass the guard without a key."""
    for host in ("localhost", "::1"):
        result, calls = _invoke_serve(monkeypatch, ["serve", "--host", host])
        assert result.exit_code == 0, result.output
        assert calls and calls[0]["host"] == host


def test_demo_nonloopback_without_key_refused(monkeypatch):
    """`pgrg demo` shares the guard — refusal fires before any DB work."""
    monkeypatch.delenv("PGRG_SERVER_API_KEY", raising=False)
    result = CliRunner().invoke(main, ["demo", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "PGRG_SERVER_API_KEY" in result.stderr
