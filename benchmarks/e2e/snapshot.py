"""Snapshot / restore the bench DB so the staged corpora can be reused
without re-running ingest.

Why this exists
---------------
Staging the 3-dataset 100-query bundle took ~2h45 (MHR dominates at 7,086s).
The corpora live in the bench Postgres at port 5437. A pg_dump of the whole
DB freezes that work as a single ~300-500 MB file you can restore in minutes.

Compatibility constraint
------------------------
A dump is only valid when restored against the **same embedder model**
(bge-large-en-v1.5, dim=1024) and the **same chunker** that produced it.
Different embedder dim => schema mismatch on the vector column. Different
chunker => stale entity-chunk and relationship-chunk links.

The dump ships a sidecar manifest (.json) with embedder, dim, chunker,
git_sha, and per-namespace row counts so a restore can sanity-check before
loading.

Usage
-----
    # Dump the current bench DB
    uv run python -m benchmarks.e2e.snapshot dump
    # → benchmarks/e2e/snapshots/2026-05-20-bench.pgcustom
    # → benchmarks/e2e/snapshots/2026-05-20-bench.manifest.json

    # Restore the latest dump (or pass --file path)
    uv run python -m benchmarks.e2e.snapshot restore

    # Inspect a manifest without restoring
    uv run python -m benchmarks.e2e.snapshot info
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL

SNAPSHOT_DIR = Path("benchmarks/e2e/snapshots")
HARNESS_CHUNKER = "auto"  # GraphRAG default; matches what ingest.py uses


def _dsn_parts(dsn: str) -> dict:
    # Minimal hand parser — psycopg's dsn parser would be cleaner but we
    # only need host/port/user/dbname for pg_dump CLI flags.
    from urllib.parse import urlparse

    u = urlparse(dsn)
    return {
        "host": u.hostname or "localhost",
        "port": str(u.port or 5432),
        "user": u.username or "postgres",
        "password": u.password or "",
        "dbname": (u.path or "/").lstrip("/") or "postgres",
    }


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: {name} not found on PATH. Install postgresql-client.")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _gather_manifest(dsn: str) -> dict:
    import psycopg

    p = _dsn_parts(dsn)
    rows: list[dict] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              d.namespace,
              count(DISTINCT d.id) AS docs,
              count(DISTINCT c.id) AS chunks,
              (SELECT count(*) FROM entities e WHERE e.namespace=d.namespace) AS entities,
              (SELECT count(*) FROM relationships r WHERE r.namespace=d.namespace) AS relationships
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.namespace LIKE 'bench_%'
            GROUP BY d.namespace
            ORDER BY d.namespace
            """
        )
        for ns, docs, chunks, ents, rels in cur.fetchall():
            rows.append(
                {
                    "namespace": ns,
                    "documents": docs,
                    "chunks": chunks,
                    "entities": ents,
                    "relationships": rels,
                }
            )
        cur.execute("SELECT pg_database_size(current_database())")
        db_size_bytes = cur.fetchone()[0]

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "embedder_model": PINNED_EMBEDDING_MODEL,
        "embedder_dim": PINNED_EMBEDDING_DIM,
        "chunker": HARNESS_CHUNKER,
        "dsn_dbname": p["dbname"],
        "dsn_host_port": f"{p['host']}:{p['port']}",
        "db_size_bytes": db_size_bytes,
        "namespaces": rows,
    }


def cmd_dump(args: argparse.Namespace) -> None:
    _require_tool("pg_dump")
    dsn = args.dsn or DEFAULT_DSN
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stem = args.label or f"{date}-bench"
    dump_path = SNAPSHOT_DIR / f"{stem}.pgcustom"
    manifest_path = SNAPSHOT_DIR / f"{stem}.manifest.json"

    manifest = _gather_manifest(dsn)
    p = _dsn_parts(dsn)
    env = os.environ.copy()
    if p["password"]:
        env["PGPASSWORD"] = p["password"]

    print(f"dumping {p['dbname']}@{p['host']}:{p['port']} -> {dump_path}", file=sys.stderr)
    subprocess.run(
        [
            "pg_dump",
            "-h", p["host"],
            "-p", p["port"],
            "-U", p["user"],
            "-d", p["dbname"],
            "-Fc",                # custom format, compressed
            "-Z", "6",            # compression level
            "-f", str(dump_path),
        ],
        check=True,
        env=env,
    )
    size = dump_path.stat().st_size
    manifest["dump_file"] = dump_path.name
    manifest["dump_size_bytes"] = size
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(
        f"\n✓ dumped {size / 1024 / 1024:.1f} MB to {dump_path}\n"
        f"✓ manifest: {manifest_path}\n",
        file=sys.stderr,
    )
    for ns in manifest["namespaces"]:
        print(
            f"  {ns['namespace']}: {ns['documents']:,} docs / {ns['chunks']:,} chunks / "
            f"{ns['entities']:,} entities / {ns['relationships']:,} relationships",
            file=sys.stderr,
        )


def _latest_dump() -> tuple[Path, Path] | None:
    if not SNAPSHOT_DIR.exists():
        return None
    dumps = sorted(SNAPSHOT_DIR.glob("*.pgcustom"))
    if not dumps:
        return None
    dump = dumps[-1]
    manifest = dump.with_suffix(".manifest.json").with_name(
        dump.stem + ".manifest.json"
    )
    return dump, manifest


def cmd_restore(args: argparse.Namespace) -> None:
    _require_tool("pg_restore")
    if args.file:
        dump_path = Path(args.file)
        manifest_path = dump_path.with_suffix("").with_name(dump_path.stem + ".manifest.json")
    else:
        latest = _latest_dump()
        if latest is None:
            sys.exit(f"no .pgcustom files in {SNAPSHOT_DIR}")
        dump_path, manifest_path = latest

    if not dump_path.exists():
        sys.exit(f"dump file not found: {dump_path}")

    # Validate compatibility before touching the DB.
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if not args.force:
            if manifest.get("embedder_dim") != PINNED_EMBEDDING_DIM:
                sys.exit(
                    f"embedder_dim mismatch: dump={manifest.get('embedder_dim')} "
                    f"current={PINNED_EMBEDDING_DIM}. Use --force to override."
                )
            if manifest.get("embedder_model") != PINNED_EMBEDDING_MODEL:
                print(
                    f"warning: embedder_model differs (dump={manifest.get('embedder_model')} "
                    f"current={PINNED_EMBEDDING_MODEL}); vectors will still match if dim agrees.",
                    file=sys.stderr,
                )
        print(f"manifest: {manifest['namespaces']}", file=sys.stderr)
    else:
        print(f"warning: no manifest at {manifest_path}; restoring blind", file=sys.stderr)

    dsn = args.dsn or DEFAULT_DSN
    p = _dsn_parts(dsn)
    env = os.environ.copy()
    if p["password"]:
        env["PGPASSWORD"] = p["password"]

    # pg_restore --clean --if-exists drops existing objects before recreating.
    print(f"restoring {dump_path} -> {p['dbname']}@{p['host']}:{p['port']}", file=sys.stderr)
    subprocess.run(
        [
            "pg_restore",
            "-h", p["host"],
            "-p", p["port"],
            "-U", p["user"],
            "-d", p["dbname"],
            "--clean",
            "--if-exists",
            "--no-owner",
            "--jobs", "4",
            str(dump_path),
        ],
        check=True,
        env=env,
    )
    print("✓ restore complete", file=sys.stderr)


def cmd_info(args: argparse.Namespace) -> None:
    if args.file:
        manifest_path = Path(args.file)
    else:
        latest = _latest_dump()
        if latest is None:
            sys.exit(f"no .pgcustom files in {SNAPSHOT_DIR}")
        manifest_path = latest[1]
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    print(json.dumps(manifest, indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="snapshot / restore the e2e bench Postgres DB")
    p.add_argument("--dsn", default=None, help=f"override DSN (default {DEFAULT_DSN})")
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("dump", help="pg_dump the bench DB + write manifest")
    pd.add_argument("--label", default=None, help="filename stem (default: YYYY-MM-DD-bench)")
    pd.set_defaults(func=cmd_dump)

    pr = sub.add_parser("restore", help="pg_restore a dump into the bench DB")
    pr.add_argument("--file", default=None, help=".pgcustom file (default: latest)")
    pr.add_argument(
        "--force",
        action="store_true",
        help="skip embedder_dim compatibility check",
    )
    pr.set_defaults(func=cmd_restore)

    pi = sub.add_parser("info", help="show a dump manifest")
    pi.add_argument("--file", default=None, help="manifest path (default: latest)")
    pi.set_defaults(func=cmd_info)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
