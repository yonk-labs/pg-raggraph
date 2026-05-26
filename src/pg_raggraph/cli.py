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


@main.command("ingest-chunkshop-table")
@click.option("--schema", "schema_name", required=True, help="Chunkshop Postgres schema")
@click.option("--table", "table_name", required=True, help="Chunkshop chunks table")
@click.option(
    "--chunkshop-dsn",
    envvar="CHUNKSHOP_DSN",
    default=None,
    help="Chunkshop Postgres DSN. Defaults to --db / PGRG_DSN.",
)
@click.option("-n", "--namespace", default=None, help="pg-raggraph namespace")
@click.option("--source-prefix", default="chunkshop", help="source_id prefix for imported docs")
@click.option("--skip-llm", is_flag=True, help="Import as vector-only chunks")
@click.option("--with-code-edges", is_flag=True, help="Also import <schema>.code_edges")
@click.option("--project-id", default=None, help="Filter code_edges by project_id")
@click.option("--min-confidence", default=0.0, type=float, help="Minimum code edge confidence")
@click.pass_context
def ingest_chunkshop_table(
    ctx,
    schema_name,
    table_name,
    chunkshop_dsn,
    namespace,
    source_prefix,
    skip_llm,
    with_code_edges,
    project_id,
    min_confidence,
):
    """Import a Chunkshop Postgres sink table via pre_chunked records."""
    kwargs = dict(ctx.obj["kwargs"])
    dsn = chunkshop_dsn or kwargs.get("dsn")
    if not dsn:
        _handle_error(ValueError("--chunkshop-dsn is required when --db/PGRG_DSN is not set"))

    async def _ingest_chunkshop_table():
        from pg_raggraph import chunkshop_bridge

        records = chunkshop_bridge.fetch_records_from_table(
            dsn,
            schema=schema_name,
            table=table_name,
            source_prefix=source_prefix,
            skip_llm=skip_llm,
        )
        if with_code_edges:
            entities, relationships = chunkshop_bridge.fetch_code_edges_from_table(
                dsn,
                schema=schema_name,
                project_id=project_id,
                min_confidence=min_confidence,
            )
            edge_rows = []
            # Reuse attach_code_edges' single-record anchoring behavior while
            # keeping fetch_code_edges_from_table's public tuple return shape.
            if entities or relationships:
                if not records:
                    raise ValueError("cannot import code_edges without chunk records")
                records[0].setdefault("entities", []).extend(entities)
                records[0].setdefault("relationships", []).extend(relationships)
                edge_rows = relationships

        if not records:
            click.echo("No Chunkshop rows found.")
            return

        rag = GraphRAG(**kwargs)
        await rag.connect()
        await rag.ingest_records(records, namespace=namespace)
        status_ns = namespace or kwargs.get("namespace")
        s = await rag.status(status_ns)
        await rag.close()
        suffix = ""
        if with_code_edges:
            suffix = f", imported code relationships: {len(edge_rows)}"
        click.echo(
            f"Imported {len(records)} Chunkshop docs. "
            f"Entities: {s['entities']}, Relationships: {s['relationships']}{suffix}"
        )

    try:
        run_async(_ingest_chunkshop_table())
    except (ConnectionError, ValueError, Exception) as e:
        _handle_error(e)


@main.command()
@click.argument("question")
@click.option(
    "-m",
    "--mode",
    default="smart",
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid", "summary"]),
    help="Retrieval mode. 'smart' (default) routes by confidence. "
    "Other modes are power-user overrides — see docs/modes.md.",
)
@click.option("-n", "--namespace", default=None)
@click.option(
    "--profile",
    default=None,
    help="Retrieval profile: cheap, balanced, accurate, 0..6, 0.0..1.0, or raw.",
)
@click.pass_context
def query(ctx, question, mode, namespace, profile):
    """Query the knowledge graph."""

    async def _query():
        kwargs = ctx.obj["kwargs"]
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()
        result = await rag.query(question, mode=mode, namespace=namespace, profile=profile)
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
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid", "summary"]),
    help="Retrieval mode. 'smart' (default) routes by confidence. "
    "Other modes are power-user overrides — see docs/modes.md.",
)
@click.option("-n", "--namespace", default=None)
@click.option(
    "--profile",
    default=None,
    help="Retrieval profile: cheap, balanced, accurate, 0..6, 0.0..1.0, or raw.",
)
@click.option(
    "--short-answer",
    is_flag=True,
    default=False,
    help="Return a short factoid answer (≤10 tokens) instead of a paragraph. "
    "Useful for SQuAD-style benchmarks (MuSiQue, HotpotQA).",
)
@click.pass_context
def ask(ctx, question, mode, namespace, profile, short_answer):
    """Ask a question — retrieves chunks and generates a grounded answer."""

    async def _ask():
        kwargs = ctx.obj["kwargs"]
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()
        result = await rag.ask(
            question,
            mode=mode,
            namespace=namespace,
            profile=profile,
            short_answer=short_answer,
        )
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


@main.command("code-impact")
@click.argument("fqn")
@click.option("-n", "--namespace", default=None, help="Namespace (default: configured)")
@click.option("--depth", type=int, default=1, help="Transitive hops (>=1)")
@click.option("--min-confidence", type=float, default=0.0, help="Min edge weight")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a tree")
@click.pass_context
def _code_impact(ctx, fqn, namespace, depth, min_confidence, as_json):
    """Show callers and callees of a code symbol (FQN) from the graph."""
    import json as _json
    from dataclasses import asdict

    from pg_raggraph.code_graph import render_impact_tree

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        ns = namespace or rag.config.namespace
        try:
            res = await rag.code_impact(
                fqn, namespace=namespace, depth=depth, min_confidence=min_confidence
            )
        finally:
            await rag.close()
        if not res.found:
            click.echo(f"symbol '{fqn}' not found in namespace '{ns}'", err=True)
            raise SystemExit(1)
        if as_json:
            click.echo(_json.dumps(asdict(res), indent=2))
        else:
            click.echo(render_impact_tree(res))

    run_async(_go())


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


# --- Migrate-embeddings subcommand group: online embedding-model migration ---


@main.group("migrate-embeddings")
def migrate_embeddings():
    """Online embedding-model migration (expand/contract column swap)."""


@migrate_embeddings.command("prepare")
@click.option("--model", "model", required=True, help="New embedding model name")
@click.option("--dim", "dim", type=int, required=True, help="New embedding dimension")
@click.option(
    "--backfill-source",
    type=click.Choice(["reembed", "chunkshop_sink"]),
    default="reembed",
)
@click.pass_context
def _me_prepare(ctx, model, dim, backfill_source):
    """Add embedding_tmp columns and record migration state."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.prepare(
                rag._db, target_model=model, target_dim=dim,
                backfill_source=backfill_source,
            )
            click.echo(f"prepared migration to {model} (dim {dim})")
        finally:
            await rag.close()

    run_async(_go())


@migrate_embeddings.command("backfill")
@click.option("--batch-size", type=int, default=256)
@click.pass_context
def _me_backfill(ctx, batch_size):
    """Re-embed all rows into embedding_tmp with the new model (resumable)."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            n = await em.backfill(rag._db, rag._get_embedder(), batch_size=batch_size)
            click.echo(f"backfilled {n} rows")
        finally:
            await rag.close()

    run_async(_go())


@migrate_embeddings.command("build-index")
@click.pass_context
def _me_build_index(ctx):
    """Build HNSW indexes on embedding_tmp (CONCURRENTLY)."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.build_index(
                rag._db,
                hnsw_m=rag.config.hnsw_m,
                hnsw_ef_construction=rag.config.hnsw_ef_construction,
            )
            click.echo("built embedding_tmp HNSW indexes")
        finally:
            await rag.close()

    run_async(_go())


@migrate_embeddings.command("status")
@click.pass_context
def _me_status(ctx):
    """Show migration phase, remaining rows, and index presence."""
    import json

    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            click.echo(json.dumps(await em.status(rag._db), indent=2, default=str))
        finally:
            await rag.close()

    run_async(_go())


@migrate_embeddings.command("cutover")
@click.pass_context
def _me_cutover(ctx):
    """Swap embedding_tmp into place as the live embedding column."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.cutover(rag._db)
            click.echo(
                "cutover complete. Restart the app with the new "
                "PGRG_EMBEDDING_DIM and PGRG_EMBEDDING_MODEL."
            )
        finally:
            await rag.close()

    run_async(_go())


@migrate_embeddings.command("finalize")
@click.pass_context
def _me_finalize(ctx):
    """Drop the preserved embedding_old columns and clear migration state."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.finalize(rag._db)
            click.echo("finalized; embedding_old dropped")
        finally:
            await rag.close()

    run_async(_go())


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
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid", "summary"]),
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
