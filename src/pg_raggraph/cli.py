"""CLI for pg-raggraph."""

from __future__ import annotations

import asyncio
import logging
import sys

import click

from pg_raggraph import GraphRAG


def run_async(coro):
    """Bridge async SDK to sync CLI."""
    return asyncio.run(coro)


@click.group()
@click.option("--db", envvar="PGRG_DSN", default=None, help="PostgreSQL DSN")
@click.option("-v", "--verbose", is_flag=True, help="Show detailed progress")
@click.pass_context
def main(ctx, db, verbose):
    """pg-raggraph — PostgreSQL-native GraphRAG."""
    ctx.ensure_object(dict)
    kwargs = {}
    if db:
        kwargs["dsn"] = db
    ctx.obj["kwargs"] = kwargs
    ctx.obj["verbose"] = verbose

    # Configure logging
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


def _handle_error(e: Exception) -> None:
    """Print friendly error and exit."""
    if isinstance(e, ConnectionError):
        click.echo(f"Error: {e}", err=True)
    elif isinstance(e, FileNotFoundError):
        click.echo(f"Error: {e}", err=True)
    elif isinstance(e, ValueError):
        click.echo(f"Error: {e}", err=True)
    else:
        click.echo(f"Error: {type(e).__name__}: {e}", err=True)
    raise SystemExit(1)


@main.command()
@click.pass_context
def init(ctx):
    """Initialize the database schema."""

    async def _init():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        status = await rag.status()
        await rag.close()
        click.echo(f"Schema v{status['schema_version']} ready.")
        click.echo(f"Embedding dim: {status['embedding_dim']}")

    try:
        run_async(_init())
    except (ConnectionError, Exception) as e:
        _handle_error(e)


@main.command()
@click.pass_context
def migrate(ctx):
    """Apply pending database migrations and exit."""

    async def _migrate():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        await rag.close()
        click.echo("Migrations applied.")

    try:
        run_async(_migrate())
    except (ConnectionError, Exception) as e:
        _handle_error(e)


@main.command()
@click.pass_context
def status(ctx):
    """Show graph statistics."""

    async def _status():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        s = await rag.status()
        await rag.close()
        click.echo(f"Namespace:     {s['namespace']}")
        click.echo(f"Documents:     {s['documents']}")
        click.echo(f"Chunks:        {s['chunks']}")
        click.echo(f"Entities:      {s['entities']}")
        click.echo(f"Relationships: {s['relationships']}")

    try:
        run_async(_status())
    except (ConnectionError, Exception) as e:
        _handle_error(e)


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("-n", "--namespace", default=None, help="Namespace")
@click.option(
    "-p",
    "--profile",
    type=click.Choice(["conservative", "balanced", "aggressive", "max"]),
    default=None,
    help="Ingestion throttle profile (default: balanced)",
)
@click.option(
    "--nice",
    type=int,
    default=None,
    help="Process nice level (0-19, higher = lower priority)",
)
@click.pass_context
def ingest(ctx, paths, namespace, profile, nice):
    """Ingest documents from paths."""
    verbose = ctx.obj["verbose"]
    kwargs = dict(ctx.obj["kwargs"])
    if profile:
        kwargs["ingest_profile"] = profile
    if nice is not None:
        kwargs["nice_level"] = nice

    def on_progress(msg):
        if verbose:
            click.echo(f"  {msg}", err=True)

    async def _ingest():
        rag = GraphRAG(**kwargs)
        await rag.connect()
        await rag.ingest(list(paths), namespace=namespace, on_progress=on_progress)
        s = await rag.status(namespace)
        await rag.close()
        click.echo(f"Ingested. Entities: {s['entities']}, Relationships: {s['relationships']}")

    try:
        run_async(_ingest())
    except (ConnectionError, FileNotFoundError, ValueError, Exception) as e:
        _handle_error(e)


@main.command()
@click.argument("question")
@click.option(
    "-m",
    "--mode",
    default="smart",
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid"]),
    help="Retrieval mode. 'smart' (default) routes by confidence. "
    "Other modes are power-user overrides — see docs/modes.md.",
)
@click.option("-n", "--namespace", default=None)
@click.pass_context
def query(ctx, question, mode, namespace):
    """Query the knowledge graph."""

    async def _query():
        kwargs = ctx.obj["kwargs"]
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()
        result = await rag.query(question, mode=mode, namespace=namespace)
        await rag.close()

        n = len(result.chunks)
        click.echo(
            f"\n--- {n} chunks retrieved "
            f"({result.latency_ms:.0f}ms) "
            f"[mode={result.query_mode} confidence={result.confidence}] ---"
        )
        for i, chunk in enumerate(result.chunks[:5], 1):
            src = chunk.document_source or "unknown"
            click.echo(f"\n[{i}] (score: {chunk.score:.3f}) {src}")
            click.echo(f"    {chunk.content[:200]}...")

        if result.entities:
            names = [e.name for e in result.entities[:10]]
            click.echo(f"\nEntities: {', '.join(names)}")

    try:
        run_async(_query())
    except (ConnectionError, ValueError, Exception) as e:
        _handle_error(e)


@main.command()
@click.argument("question")
@click.option(
    "-m",
    "--mode",
    default="smart",
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid"]),
    help="Retrieval mode. 'smart' (default) routes by confidence. "
    "Other modes are power-user overrides — see docs/modes.md.",
)
@click.option("-n", "--namespace", default=None)
@click.option(
    "--short-answer",
    is_flag=True,
    default=False,
    help="Return a short factoid answer (≤10 tokens) instead of a paragraph. "
    "Useful for SQuAD-style benchmarks (MuSiQue, HotpotQA).",
)
@click.pass_context
def ask(ctx, question, mode, namespace, short_answer):
    """Ask a question — retrieves chunks and generates a grounded answer."""

    async def _ask():
        kwargs = ctx.obj["kwargs"]
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()
        result = await rag.ask(question, mode=mode, namespace=namespace, short_answer=short_answer)
        await rag.close()

        click.echo(f"\n{result.answer}\n")
        click.echo(
            f"--- {len(result.chunks)} chunks "
            f"({result.latency_ms:.0f}ms) "
            f"[mode={result.query_mode} confidence={result.confidence}] ---"
        )
        for i, chunk in enumerate(result.chunks[:3], 1):
            src = chunk.document_source or "unknown"
            click.echo(f"[{i}] {src} (score: {chunk.score:.3f})")

    try:
        run_async(_ask())
    except (ConnectionError, ValueError, Exception) as e:
        _handle_error(e)


@main.command()
@click.option("-n", "--namespace", required=True, help="Namespace to delete")
@click.confirmation_option(prompt="Are you sure?")
@click.pass_context
def delete(ctx, namespace):
    """Delete all data in a namespace."""

    async def _delete():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        await rag.delete(namespace)
        await rag.close()
        click.echo(f"Namespace '{namespace}' deleted.")

    try:
        run_async(_delete())
    except (ConnectionError, ValueError, Exception) as e:
        _handle_error(e)


@main.command("mcp-serve")
@click.pass_context
def mcp_serve(ctx):
    """Run the MCP server over stdio for Claude Desktop, Cursor, etc."""
    try:
        from pg_raggraph.mcp_server import run_stdio
    except ImportError as e:
        click.echo(f"MCP server unavailable: {e}")
        click.echo("Install with: pip install pg-raggraph[mcp]")
        raise SystemExit(1)

    try:
        run_async(run_stdio(**ctx.obj["kwargs"]))
    except (ConnectionError, ValueError, Exception) as e:
        _handle_error(e)


@main.command()
@click.option("-p", "--port", default=8080, help="Port")
@click.pass_context
def serve(ctx, port):
    """Launch the API server."""
    try:
        import uvicorn

        from pg_raggraph.server import create_app
    except ImportError:
        click.echo("Install server extras: pip install pg-raggraph[server]")
        raise SystemExit(1)
    app = create_app(**ctx.obj["kwargs"])
    uvicorn.run(app, host="0.0.0.0", port=port)


@main.command()
@click.option("-p", "--port", default=8080, help="Port for web UI")
@click.pass_context
def demo(ctx, port):
    """Run the demo — ingest sample docs and launch web UI."""
    import webbrowser

    try:
        import uvicorn

        from pg_raggraph.server import create_app
    except ImportError:
        click.echo("Install demo extras: pip install pg-raggraph[demo]")
        raise SystemExit(1)

    async def _setup():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()

        import pathlib

        project_root = pathlib.Path(__file__).parent.parent.parent
        demo_paths = []
        for candidate in [
            project_root / "research",
            project_root / "tests" / "fixtures",
        ]:
            if candidate.exists():
                demo_paths.append(str(candidate))
                break

        if demo_paths:
            click.echo(f"Ingesting demo corpus from {demo_paths[0]}...")
            await rag.ingest(demo_paths, namespace="demo")
            status = await rag.status("demo")
            click.echo(
                f"Done: {status['documents']} docs, "
                f"{status['entities']} entities, "
                f"{status['relationships']} relationships"
            )
        else:
            click.echo("No demo corpus found. Launching UI anyway.")
        await rag.close()

    try:
        run_async(_setup())
    except (ConnectionError, Exception) as e:
        _handle_error(e)
        return

    click.echo(f"\nStarting web UI at http://localhost:{port}")
    click.echo("Press Ctrl+C to stop.\n")
    webbrowser.open(f"http://localhost:{port}")

    app = create_app(**ctx.obj["kwargs"])
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


# --- Devmem subcommand: developer knowledge base with dev-tuned defaults ---


def _devmem_kwargs(ctx_kwargs: dict) -> dict:
    """Build the kwargs for a devmem GraphRAG instance.

    Defaults to dev extraction prompt and devmem namespace. Anything in
    ctx_kwargs overrides these defaults.
    """
    kw = {
        "namespace": "devmem",
        "extraction_prompt": "dev",
    }
    kw.update(ctx_kwargs)
    return kw


@main.group()
@click.pass_context
def devmem(ctx):
    """Developer knowledge base (dev-tuned defaults).

    Uses dev-specific extraction prompt, code-aware chunking, and
    the 'devmem' namespace by default. Run 'pgrg devmem --help' for
    available subcommands.
    """
    pass


@devmem.command("init")
@click.pass_context
def devmem_init(ctx):
    """Initialize the devmem namespace."""

    async def _init():
        rag = GraphRAG(**_devmem_kwargs(ctx.obj["kwargs"]))
        await rag.connect()
        s = await rag.status()
        await rag.close()
        click.echo(f"devmem namespace ready (schema v{s['schema_version']}).")

    try:
        run_async(_init())
    except Exception as e:
        _handle_error(e)


@devmem.command("ingest")
@click.argument("paths", nargs=-1, required=True)
@click.option("-n", "--namespace", default=None, help="Override devmem namespace")
@click.option(
    "-p",
    "--profile",
    type=click.Choice(["conservative", "balanced", "aggressive", "max"]),
    default=None,
)
@click.pass_context
def devmem_ingest(ctx, paths, namespace, profile):
    """Ingest code, docs, and engineering artifacts."""
    verbose = ctx.obj["verbose"]
    kwargs = _devmem_kwargs(ctx.obj["kwargs"])
    if namespace:
        kwargs["namespace"] = namespace
    if profile:
        kwargs["ingest_profile"] = profile

    def on_progress(msg):
        if verbose:
            click.echo(f"  {msg}", err=True)

    async def _ingest():
        rag = GraphRAG(**kwargs)
        await rag.connect()
        await rag.ingest(list(paths), on_progress=on_progress)
        s = await rag.status()
        await rag.close()
        click.echo(
            f"devmem: {s['documents']} docs, {s['entities']} entities, "
            f"{s['relationships']} relationships"
        )

    try:
        run_async(_ingest())
    except Exception as e:
        _handle_error(e)


@devmem.command("ask")
@click.argument("question")
@click.option(
    "-m",
    "--mode",
    default="smart",
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid"]),
)
@click.option("-n", "--namespace", default=None)
@click.pass_context
def devmem_ask(ctx, question, mode, namespace):
    """Ask a question against your developer knowledge base."""
    kwargs = _devmem_kwargs(ctx.obj["kwargs"])
    if namespace:
        kwargs["namespace"] = namespace

    async def _ask():
        rag = GraphRAG(**kwargs)
        await rag.connect()
        result = await rag.query(question, mode=mode)
        await rag.close()

        click.echo(
            f"\n--- {len(result.chunks)} chunks "
            f"({result.latency_ms:.0f}ms) "
            f"[{result.query_mode} confidence={result.confidence}] ---"
        )
        for i, chunk in enumerate(result.chunks[:5], 1):
            src = chunk.document_source or "unknown"
            click.echo(f"\n[{i}] (score: {chunk.score:.3f}) {src}")
            click.echo(f"    {chunk.content[:250]}...")

        if result.entities:
            names = [e.name for e in result.entities[:10]]
            click.echo(f"\nEntities: {', '.join(names)}")
        if result.relationships:
            click.echo(f"\nRelationships: {len(result.relationships)} found")

    try:
        run_async(_ask())
    except Exception as e:
        _handle_error(e)


@devmem.command("status")
@click.option("-n", "--namespace", default=None)
@click.pass_context
def devmem_status(ctx, namespace):
    """Show devmem namespace stats."""
    kwargs = _devmem_kwargs(ctx.obj["kwargs"])
    if namespace:
        kwargs["namespace"] = namespace

    async def _status():
        rag = GraphRAG(**kwargs)
        await rag.connect()
        s = await rag.status()
        await rag.close()
        click.echo(f"Namespace:     {s['namespace']}")
        click.echo(f"Documents:     {s['documents']}")
        click.echo(f"Chunks:        {s['chunks']}")
        click.echo(f"Entities:      {s['entities']}")
        click.echo(f"Relationships: {s['relationships']}")

    try:
        run_async(_status())
    except Exception as e:
        _handle_error(e)
