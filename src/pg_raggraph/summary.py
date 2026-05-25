"""Deterministic, LLM-free summary of retrieved chunks via lede v0.4 hints.

Builds query-derived hints (top_terms seeds, optional lede-spacy lemma /
synonym / similar expansion) and runs lede's hint-biased summarize over the
concatenated retrieved chunks. No LLM, no network, no DB.

Optional deps for expansion — install with:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm   # lemma + synonyms
    python -m spacy download en_core_web_md   # also enables "similar"
"""

from __future__ import annotations

import logging
import re
import warnings

from pg_raggraph.chunking import token_count
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult

logger = logging.getLogger("pg_raggraph.summary")

# spaCy expansion kinds per query_expansion tier.
_EXPANSION_KINDS: dict[str, tuple[str, ...]] = {
    "off": (),
    "lemma": ("lemma",),
    "moderate": ("lemma", "synonyms"),
    "aggressive": ("lemma", "synonyms", "similar"),
}


def _has_vector_model() -> bool:
    """True if a spaCy model with word vectors (md/lg) is installed.

    The "similar" expansion kind needs vectors; sm has none.
    """
    try:
        import spacy.util
    except ModuleNotFoundError:
        return False
    return spacy.util.is_package("en_core_web_md") or spacy.util.is_package("en_core_web_lg")


def _resolve_expansion_tier(tier: str) -> str:
    """Resolve query_expansion tier, degrading 'aggressive' → 'moderate' when
    no vector model (md/lg) is installed. Emits exactly one warning on degrade.
    """
    if tier == "aggressive" and not _has_vector_model():
        warnings.warn(
            "query_expansion='aggressive' needs en_core_web_md or en_core_web_lg "
            "for the 'similar' expansion; falling back to 'moderate'. "
            "Install with: python -m spacy download en_core_web_md",
            stacklevel=2,
        )
        return "moderate"
    return tier


def _seed_weights(question: str, n: int) -> dict[str, float]:
    """Top-N salient terms from the question, weighted by rank position.

    Rank 0 → heaviest, decaying linearly. Deterministic. Returns {} when lede
    yields no terms (e.g. empty or stopword-only query).
    """
    from lede.extract import top_terms

    terms = [t for t in top_terms(question, n=n) if t and t.strip()]
    if not terms:
        return {}
    denom = len(terms) + 1
    return {t: round(1.0 - (i / denom), 4) for i, t in enumerate(terms)}


def build_hints(question: str, config: PGRGConfig) -> dict[str, float]:
    """Query → ordered, weighted, capped hint dict for lede.summarize.

    1. Seed terms via lede.extract.top_terms (weighted by rank).
    2. Optional expansion via lede_spacy.expand_hints, gated by
       config.query_expansion. 'aggressive' degrades to 'moderate' (one
       warning) when no md/lg model is present. If lede-spacy isn't
       installed, expansion is skipped silently and raw seeds are used.
    3. Cap at config.max_hints (highest weight first; deterministic tie-break).
    """
    seeds = _seed_weights(question, config.summary_seed_terms)
    if not seeds:
        return {}

    tier = _resolve_expansion_tier(config.query_expansion)
    kinds = _EXPANSION_KINDS[tier]
    hints: dict[str, float] = dict(seeds)

    if kinds:
        try:
            from lede_spacy import expand_hints

            hints = dict(
                expand_hints(
                    seeds,
                    kinds=kinds,
                    top_k=config.expand_top_k,
                    expand_weight=config.expand_weight,
                )
            )
        except ImportError as exc:
            # lede-spacy not installed OR a required sub-dep (e.g. nltk for
            # 'synonyms') is missing.  Fall back to raw seeds silently.
            logger.info("lede-spacy expansion unavailable (%s); using raw seed terms.", exc)
            hints = dict(seeds)

    if len(hints) > config.max_hints:
        ordered = sorted(hints.items(), key=lambda kv: (-kv[1], kv[0]))
        hints = dict(ordered[: config.max_hints])
    return hints


def expand_query_terms(question: str, config: PGRGConfig) -> list[str]:
    """Expanded BM25 retrieval terms (deterministic, capped). Never raises.

    Combines lexical expansion (lemma/synonym via lede_spacy, gated by
    config.retrieval_expansion) with config.retrieval_alias_map (named-entity
    aliases WordNet can't bridge). Returns [] when nothing applies. Degrades to
    raw seeds when lede-spacy/nltk is unavailable.
    """
    terms: set[str] = set()
    q_lower = question.lower()

    for key, aliases in (config.retrieval_alias_map or {}).items():
        if re.search(rf"(?<!\w){re.escape(key.lower())}(?!\w)", q_lower):
            terms.update(a.lower() for a in aliases)

    tier = config.retrieval_expansion
    if tier != "off":
        try:
            seeds = _seed_weights(question, config.summary_seed_terms)
        except ImportError:
            # lede core not installed — honor the "never raises" contract by
            # degrading to alias-only expansion.
            seeds = {}
        if seeds:
            resolved = _resolve_expansion_tier(tier)
            kinds = _EXPANSION_KINDS[resolved]
            if kinds:
                try:
                    from lede_spacy import expand_hints

                    expanded = expand_hints(
                        seeds,
                        kinds=kinds,
                        top_k=config.expand_top_k,
                        expand_weight=config.expand_weight,
                    )
                    terms.update(t.lower() for t in expanded)
                except ImportError:
                    terms.update(seeds)
            else:
                terms.update(seeds)

    out = sorted(t for t in terms if t and t.strip())
    return out[: config.max_hints]


def chunks_text(result: QueryResult) -> str:
    """Raw retrieved-chunk context in the same order retrieval returned it."""
    return "\n\n".join(c.content for c in result.chunks)


def context_token_count(result: QueryResult) -> int:
    """Token count for the raw retrieved context."""
    return token_count(chunks_text(result))


def should_summarize_context(context_tokens: int, config: PGRGConfig) -> bool:
    """Return whether summary compression is worth applying.

    Summarization is most valuable when retrieved context is large enough that
    raw chunks are meaningfully expensive or noisy. Below the configured gate,
    callers should keep the raw chunks/context instead of compressing away
    potentially useful multi-hop detail.
    """
    return context_tokens >= config.summary_min_context_tokens


def adaptive_summary_length(
    n_chunks: int,
    config: PGRGConfig,
    context_tokens: int | None = None,
) -> int:
    """Scale the summary char budget by retrieved context size, bounded.

    Returns summary_max_length (floor) at <= summary_length_floor_chunks and
    summary_max_length_ceiling at >= summary_length_ceiling_chunks, linear
    between. When context_tokens is supplied, the budget scales from raw
    context size using summary_target_compression_ratio, which better matches
    10 / 100 / 1000 chunk regimes than chunk-count alone. Non-decreasing.
    """
    floor_len = config.summary_max_length
    ceil_len = max(config.summary_max_length_ceiling, floor_len)
    if context_tokens is not None:
        target_len = int(context_tokens * 4 * config.summary_target_compression_ratio)
        return min(ceil_len, max(floor_len, target_len))

    lo = config.summary_length_floor_chunks
    hi = config.summary_length_ceiling_chunks
    if n_chunks <= lo or hi <= lo:
        return floor_len
    if n_chunks >= hi:
        return ceil_len
    frac = (n_chunks - lo) / (hi - lo)
    return int(floor_len + frac * (ceil_len - floor_len))


def adaptive_fact_count(context_tokens: int, config: PGRGConfig) -> int:
    """Scale extracted key-fact count for larger retrieved contexts."""
    base = max(0, config.summary_max_facts)
    ceil_count = max(base, config.summary_max_facts_ceiling)
    if context_tokens <= config.summary_min_context_tokens:
        return base
    extra = (context_tokens - config.summary_min_context_tokens) // max(
        1, config.summary_fact_tokens_per_extra
    )
    return min(ceil_count, base + int(extra))


def summarize_chunks(question: str, result: QueryResult, config: PGRGConfig) -> str:
    """Hint-biased lede summary over the retrieved chunks.

    Concatenates chunk contents and runs lede.summarize with query-derived
    hints. When config.summary_keep_headings is set, lede re-injects each
    selected sentence's enclosing heading (and pins the doc title) so section
    context survives extractive compression — a no-op on heading-less corpora.
    When config.summary_include_facts is set, hint-biased lede.key_facts are
    appended — this recovered the multi-hop accuracy gap in the bake-off
    (summary_facts ≈ raw chunks at ~67% token reduction; facts, not length,
    are what close the gap). Returns "" when there are no chunks. Deterministic
    given the same (question, chunk set, config).
    """
    if not result.chunks:
        return ""
    from lede import summarize as lede_summarize

    text = chunks_text(result)
    ctx_tokens = token_count(text)
    if config.summary_skip_small_contexts and not should_summarize_context(ctx_tokens, config):
        return text

    hints = build_hints(question, config) or None
    summary = lede_summarize(
        text,
        max_length=adaptive_summary_length(len(result.chunks), config, ctx_tokens),
        hints=hints,
        hint_focus=config.summary_hint_focus,
        hint_mode="soft",
        keep_headings=config.summary_keep_headings,
        include_toc=config.summary_include_toc,
    ).summary

    if config.summary_include_facts:
        try:
            from lede.extract import key_facts

            facts = key_facts(
                text,
                max_facts=adaptive_fact_count(ctx_tokens, config),
                hints=hints,
                hint_focus=config.summary_hint_focus,
                hint_mode="soft",
            )
        except ImportError:
            facts = ()
        if facts:
            summary = summary + "\n\nKey facts:\n" + "\n".join(f"- {f}" for f in facts)
    return summary
