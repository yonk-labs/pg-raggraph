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
            summaries = chunkshop_bridge.summaries_by_fqn(records)
            entities, relationships = chunkshop_bridge.fetch_code_edges_from_table(
                dsn,
                schema=schema_name,
                project_id=project_id,
                min_confidence=min_confidence,
                summaries=summaries,
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
@click.option("-n", "--namespace", default=None, help="Namespace to drain (default: all)")
@click.option("--batch-size", default=4, type=int, show_default=True, help="Docs per claim")
@click.option(
    "--max-iterations",
    default=0,
    type=int,
    show_default=True,
    help="Stop after N iterations (0 = unlimited; ignored with --once)",
)
@click.option(
    "--rate-limit-rps",
    default=0.0,
    type=float,
    show_default=True,
    help="Cap docs/second across iterations (0 = unlimited)",
)
@click.option(
    "--once",
    is_flag=True,
    help="Run exactly one claim+extract iteration and exit (overrides --max-iterations)",
)
@click.option(
    "--include-failed",
    is_flag=True,
    help="Reset 'failed' docs to 'pending' at startup so they're retried",
)
@click.option(
    "--daemon",
    is_flag=True,
    help=(
        "Long-running mode: keep polling for pending docs. Handles SIGTERM/SIGINT "
        "gracefully — finishes the in-flight batch, then exits 0."
    ),
)
@click.option(
    "--poll-interval",
    default=2.0,
    type=float,
    show_default=True,
    help="Seconds to wait between empty-queue checks in --daemon mode",
)
@click.pass_context
def extract(
    ctx,
    namespace,
    batch_size,
    max_iterations,
    rate_limit_rps,
    once,
    include_failed,
    daemon,
    poll_interval,
):
    """Drain documents.graph_status='pending' — run background extraction.

    Exits 0 when the queue is empty (or --once / --max-iterations is reached).
    Workers can run concurrently safely; SKIP LOCKED guarantees no overlap.
    """
    import signal

    from pg_raggraph.backfill import (
        claim_pending,
        extract_documents,
        release_processing,
    )

    if batch_size < 1:
        raise click.BadParameter("--batch-size must be >= 1")
    if max_iterations < 0:
        raise click.BadParameter("--max-iterations must be >= 0")
    if rate_limit_rps < 0:
        raise click.BadParameter("--rate-limit-rps must be >= 0")
    if poll_interval <= 0:
        raise click.BadParameter("--poll-interval must be > 0")
    if daemon and once:
        raise click.BadParameter("--daemon and --once are mutually exclusive")

    async def _extract():
        kwargs = dict(ctx.obj["kwargs"])
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()

        shutdown = asyncio.Event()
        if daemon:
            # Cooperative shutdown: signal handlers just set the event so
            # the loop finishes the in-flight batch atomically before exit.
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, shutdown.set)
                except NotImplementedError:
                    # Windows event loops don't support add_signal_handler;
                    # those users get harder shutdowns (KeyboardInterrupt).
                    pass

        try:
            # Reaper first — recover from prior crashes that left rows in
            # 'processing'. Scoped to this worker's --namespace so a peer
            # worker running against a different namespace doesn't have its
            # in-flight claims stolen. When --namespace is omitted (drain
            # everything), release_processing logs a warning before doing
            # the global reap; operators running multi-tenant deployments
            # should always pass --namespace.
            await release_processing(rag.db, namespace=namespace)

            if include_failed:
                if namespace:
                    await rag.db.execute(
                        "UPDATE documents SET graph_status = 'pending', graph_error = NULL "
                        "WHERE namespace = %s AND graph_status = 'failed'",
                        (namespace,),
                    )
                else:
                    await rag.db.execute(
                        "UPDATE documents SET graph_status = 'pending', graph_error = NULL "
                        "WHERE graph_status = 'failed'"
                    )

            totals = {"claimed": 0, "ready": 0, "failed": 0, "ents": 0, "rels": 0}
            iteration = 0
            import time as _time

            while True:
                if shutdown.is_set():
                    click.echo("Shutdown signal received; exiting cleanly.", err=True)
                    break

                iteration += 1
                iter_started = _time.perf_counter()
                claim_t0 = _time.perf_counter()
                ids = await claim_pending(rag.db, namespace, batch_size)
                # claim is metric-emitted on EVERY iteration including empty
                # ones so an operator can spot a daemon that's polling a
                # queue but never finding work (e.g. wrong namespace).
                rag._emit_metric(
                    "pgrg.backfill.claim",
                    namespace=namespace,
                    batch_size=batch_size,
                    claimed=len(ids),
                    latency_ms=(_time.perf_counter() - claim_t0) * 1000,
                )
                if not ids:
                    if daemon:
                        # Wait poll_interval or until shutdown — whichever
                        # comes first. asyncio.wait_for raises TimeoutError
                        # on the timeout branch; treat that as "keep polling."
                        try:
                            await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
                        except asyncio.TimeoutError:
                            pass
                        # Re-check at top of loop (shutdown may now be set).
                        continue
                    click.echo(f"Queue drained after {iteration - 1} iteration(s).", err=True)
                    break

                stats = await extract_documents(rag, ids, namespace=namespace)
                totals["claimed"] += stats.claimed
                totals["ready"] += stats.ready
                totals["failed"] += stats.failed
                totals["ents"] += stats.entities
                totals["rels"] += stats.relationships
                click.echo(
                    f"[iter {iteration}] claimed={stats.claimed} ready={stats.ready} "
                    f"failed={stats.failed} ents={stats.entities} rels={stats.relationships}",
                    err=True,
                )

                # Per-iteration queue depth gives operators an at-a-glance
                # "is this thing converging?" signal. Only meaningful when
                # the worker has scoped to a namespace (the global summary
                # is too expensive on large multi-tenant DBs).
                if namespace:
                    try:
                        summary = await rag._graph_status_summary(namespace)
                        rag._emit_metric(
                            "pgrg.backfill.queue_depth",
                            namespace=namespace,
                            **summary,
                        )
                    except Exception as e:
                        # A summary scan should never break the loop.
                        logging.getLogger("pg_raggraph.cli").debug(
                            "queue_depth metric failed: %s", e
                        )

                if not daemon and (once or (max_iterations and iteration >= max_iterations)):
                    break

                if rate_limit_rps > 0:
                    # Target a per-iteration wall-time floor so the worker
                    # never exceeds the configured docs/sec.
                    elapsed = _time.perf_counter() - iter_started
                    floor = len(ids) / rate_limit_rps
                    if elapsed < floor:
                        try:
                            await asyncio.wait_for(shutdown.wait(), timeout=floor - elapsed)
                        except asyncio.TimeoutError:
                            pass

            click.echo(
                f"Done: {totals['ready']} ready / {totals['failed']} failed "
                f"of {totals['claimed']} claimed. {totals['ents']} entities, "
                f"{totals['rels']} relationships."
            )
        finally:
            await rag.close()

    try:
        run_async(_extract())
    except Exception as e:
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
                rag._db,
                target_model=model,
                target_dim=dim,
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


# ---------------------------------------------------------------------------
# pgrg ab-gate group — A/B retrieval benchmark harness + runner (#48 + #49)
# ---------------------------------------------------------------------------


@main.group("ab-gate")
def ab_gate():
    """A/B retrieval benchmark harness (chunkshop ↔ pg-raggraph A/B gate).

    Subcommands:
      materialize — build graph entities from imported fact/cooccur surfaces.
      run         — run the {corpora × modes} matrix and write per-cell JSONs.
      verdict     — apply the contract §3 combiner to runner output + write report.

    See ``docs/cookbook/ab-gate.md`` for the full operator workflow.
    """


@ab_gate.command("run")
@click.option(
    "--corpus",
    "corpora",
    multiple=True,
    required=True,
    help="Corpus id (= namespace). Repeat once per corpus; pair 1:1 with --gold.",
)
@click.option(
    "--gold",
    "gold_paths",
    multiple=True,
    required=True,
    type=click.Path(dir_okay=False),
    help="Gold-Q YAML file. Pair 1:1 with --corpus (same flag count, same order).",
)
@click.option(
    "--mode",
    "modes",
    multiple=True,
    required=True,
    type=click.Choice(["naive_vector", "graph_leg", "hybrid"], case_sensitive=False),
    help="Retrieval mode. Repeat to run multiple modes.",
)
@click.option(
    "--top-k",
    default=10,
    type=int,
    show_default=True,
    help="Top-K items per question.",
)
@click.option(
    "--out",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False),
    help="Output directory. Created if missing. Existing files are overwritten.",
)
@click.pass_context
def ab_gate_run(ctx, corpora, gold_paths, modes, top_k, output_dir):
    """Run the A/B matrix and write per-(corpus, mode) JSONs + manifest.json."""
    from pathlib import Path

    from pg_raggraph.ab_gate import load_gold_questions, run_ab_matrix

    if len(corpora) != len(gold_paths):
        raise click.BadParameter(
            f"--corpus/--gold pairing mismatch: got {len(corpora)} corpora and "
            f"{len(gold_paths)} gold files. Pass exactly one --gold per --corpus, "
            f"in matching order.",
            ctx=ctx,
        )
    output_dir = Path(output_dir)

    async def _run():
        kwargs = dict(ctx.obj["kwargs"])
        rag = GraphRAG(**kwargs)
        await rag.connect()
        try:
            gold_per_corpus: dict[str, list] = {}
            for corpus_id, gold_path in zip(corpora, gold_paths):
                gold_per_corpus[corpus_id] = load_gold_questions(Path(gold_path))
            paths = await run_ab_matrix(
                rag,
                corpora=list(corpora),
                modes=list(modes),
                gold_questions_per_corpus=gold_per_corpus,
                output_dir=output_dir,
                top_k=top_k,
            )
            click.echo(f"Wrote {len(paths)} per-(corpus, mode) files to {output_dir}")
            click.echo(f"Manifest: {output_dir / 'manifest.json'}")
        finally:
            await rag.close()

    try:
        run_async(_run())
    except Exception as e:
        _handle_error(e)


@ab_gate.command("materialize")
@click.option(
    "--namespace",
    "-n",
    "namespaces",
    multiple=True,
    required=True,
    help="Corpus id (= namespace) to materialize. Repeat for multiple.",
)
@click.pass_context
def ab_gate_materialize(ctx, namespaces):
    """Materialize graph entities from imported fact/cooccur surfaces.

    Prerequisite for the graph_leg of `pgrg ab-gate run`: reads every
    distinct fact subject/object + cooccur node from the corpus's chunks
    (imported via `pgrg ingest-chunkshop-table`) and inserts one entity per
    distinct surface so `resolve_entity_lookup` can find them. Idempotent.
    """
    from pg_raggraph.ab_gate import materialize_entities_from_corpus

    async def _run():
        kwargs = dict(ctx.obj["kwargs"])
        rag = GraphRAG(**kwargs)
        await rag.connect()
        try:
            for ns in namespaces:
                count = await materialize_entities_from_corpus(rag, ns)
                click.echo(f"{ns}: materialized {count} new entities")
        finally:
            await rag.close()

    try:
        run_async(_run())
    except Exception as e:
        _handle_error(e)


@ab_gate.command("verdict")
@click.option(
    "--runs",
    "runs_dir",
    required=True,
    type=click.Path(file_okay=False, exists=True),
    help="Directory of per-(corpus, mode) JSONs from `ab-gate run`.",
)
@click.option(
    "--out",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False),
    help="Where to write verdict.json / verdict.md / latency.json.",
)
@click.option(
    "--judge-provider",
    default="none",
    show_default=True,
    help="LLM judge provider kind: none | mock | openai | openai-compatible | "
    "anthropic | ollama | gemini | openrouter. 'none' skips the judge metric "
    "(recall@10 + MRR still decide the verdict).",
)
@click.option("--judge-model", default=None, help="Judge model name.")
@click.option("--judge-base-url", default=None, help="Judge endpoint base URL.")
@click.option(
    "--judge-api-key-env",
    default=None,
    help="Env var holding the judge API key (e.g. OPENAI_API_KEY).",
)
@click.pass_context
def ab_gate_verdict(
    ctx, runs_dir, output_dir, judge_provider, judge_model, judge_base_url, judge_api_key_env
):
    """Apply the contract §3 combiner to runner output and write the report."""
    from pathlib import Path

    from pg_raggraph.ab_gate import compute_verdict, write_verdict_report
    from pg_raggraph.ab_gate.io import ABRunnerOutput

    runs = Path(runs_dir)
    cell_files = sorted(p for p in runs.glob("*__*.json") if p.name != "manifest.json")
    if not cell_files:
        raise click.BadParameter(
            f"no per-(corpus, mode) JSON files (<corpus>__<mode>.json) found in {runs_dir}",
            ctx=ctx,
        )

    judge_config = None
    if judge_provider.lower() != "none":
        judge_config = {
            "provider": {
                "kind": judge_provider.lower(),
                "model": judge_model,
                "base_url": judge_base_url,
                "api_key_env": judge_api_key_env,
            }
        }

    import json as _json

    outputs = [ABRunnerOutput.from_dict(_json.loads(p.read_text())) for p in cell_files]
    # Latency rows for the informational latency.json (§3.6).
    latency_rows = [
        {
            "corpus": o.corpus_id,
            "mode": o.mode,
            "question_id": c.question_id,
            "latency_ms": c.latency_ms,
        }
        for o in outputs
        for c in o.results
    ]

    try:
        verdict = compute_verdict(outputs, judge_config=judge_config)
        write_verdict_report(verdict, out_dir=Path(output_dir), latency_rows=latency_rows)
        click.echo(f"Verdict: {verdict.label}")
        click.echo(verdict.rationale)
        click.echo(f"\nReport written to {output_dir}/verdict.json + verdict.md")
    except Exception as e:
        _handle_error(e)
