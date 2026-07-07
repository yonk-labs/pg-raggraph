"""Entity/relationship extraction using LLM (OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)

# Common false-positive entity names — words that look like names but aren't.
# The LLM frequently picks these up from vocabulary files, stop word lists,
# and generic prose. Filter them out before storing.
_ENTITY_BLOCKLIST = frozenset(
    {
        # Generic words that often get tagged as entities
        "user",
        "users",
        "default",
        "example",
        "foo",
        "bar",
        "baz",
        "test",
        "data",
        "value",
        "item",
        "thing",
        "object",
        "string",
        "none",
        "null",
        "true",
        "false",
        "yes",
        "no",
        "n/a",
        "tbd",
        "todo",
        # Common single-char / short "names" from tokenizers
        "a",
        "b",
        "c",
        "d",
        "e",
        "x",
        "y",
        "z",
        # Typical vocab file tokens
        "the",
        "and",
        "or",
        "if",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
    }
)


def _is_valid_entity(name: str, description: str = "") -> bool:
    """Filter out false-positive entities.

    Rejects entities that are:
    - Too short (<= 2 chars)
    - In the blocklist (common generic words)
    - All numeric
    - Only punctuation
    - Starting with ## (BERT wordpiece tokens)
    """
    if not name or len(name) < 2:
        return False
    cleaned = name.strip()
    if cleaned.lower() in _ENTITY_BLOCKLIST:
        return False
    if cleaned.startswith("##"):  # BERT wordpiece tokens
        return False
    if cleaned.isdigit():
        return False
    if not any(c.isalnum() for c in cleaned):
        return False
    return True


def filter_extraction(result: ExtractionResult) -> ExtractionResult:
    """Remove invalid entities and dangling relationships."""
    valid_entities = [e for e in result.entities if _is_valid_entity(e.name, e.description)]
    valid_names = {e.name for e in valid_entities}
    # Drop relationships that reference filtered-out entities
    valid_rels = [
        r for r in result.relationships if r.source in valid_names and r.target in valid_names
    ]
    return ExtractionResult(entities=valid_entities, relationships=valid_rels)


def _parse_extraction(parsed: object) -> ExtractionResult:
    """Build a filtered ExtractionResult from parsed LLM JSON, leniently.

    Validates entities and relationships one item at a time, skipping only the
    malformed ones. A single bad item — e.g. a relationship the LLM emitted
    without the required ``target`` field — no longer discards the whole
    chunk's extraction. This extends the leniency already applied to ``weight``
    in :class:`ExtractedRelationship` to the parse step itself. See issue #69.
    """
    if not isinstance(parsed, dict):
        logger.warning(
            "Extraction returned non-object JSON (%s); dropping chunk",
            type(parsed).__name__,
        )
        return ExtractionResult()

    def _items(model_cls, raw):
        out = []
        for item in raw or []:
            try:
                out.append(model_cls.model_validate(item))
            except ValidationError as e:
                logger.debug("Skipping malformed %s: %s", model_cls.__name__, e)
        return out

    return filter_extraction(
        ExtractionResult(
            entities=_items(ExtractedEntity, parsed.get("entities")),
            relationships=_items(ExtractedRelationship, parsed.get("relationships")),
        )
    )


logger = logging.getLogger("pg_raggraph.extraction")

EXTRACTION_SYSTEM_PROMPT = """\
You are an expert knowledge graph extractor. \
Given text, extract entities and relationships.

Return JSON with this structure:
{"entities": [...], "relationships": [...]}

Entity fields: name, entity_type, description
Relationship fields: source, target, rel_type, description, weight

Rules:
- Use proper nouns and specific names for entities
- entity_type: lowercase (person, organization, technology, concept)
- rel_type: UPPER_SNAKE_CASE (DEVELOPED_BY, USES, PART_OF, RELATED_TO)
- Only extract explicit facts from the text
- Keep descriptions concise (1 sentence)
- Normalize entity names (consistent casing)"""


DEV_EXTRACTION_PROMPT = """\
You are an expert at extracting knowledge graphs from engineering documents.
Given text from code, PRs, ADRs, incidents, runbooks, or technical docs,
extract entities and relationships.

Return JSON with this structure:
{"entities": [...], "relationships": [...]}

Entity fields: name, entity_type, description
Relationship fields: source, target, rel_type, description, weight

Preferred entity types (use these when applicable):
- person      (engineers, authors, reviewers, owners)
- service     (microservices, APIs, applications)
- library     (dependencies, packages, frameworks)
- file        (source file paths)
- commit      (git SHAs, PR numbers)
- incident    (INC-NNN, outages, postmortems)
- ticket      (JIRA-NNN, bug reports, feature requests)
- adr         (architecture decision records)
- concept     (patterns, protocols, algorithms)
- tool        (CLIs, IDEs, deployment tools)
- environment (production, staging, kubernetes namespaces)

Preferred relationship types:
- OWNS                  (person → service/library/file)
- MAINTAINS             (person → anything)
- TOUCHED / AUTHORED    (person → commit/file)
- DEPENDS_ON            (service → library/service)
- CALLS / USES          (service → service)
- CAUSED                (thing → incident)
- FIXED_BY              (incident → commit/person)
- REFERENCES / CITES    (doc → doc/adr)
- PART_OF               (file → service; service → team)
- DEPLOYED_TO           (service → environment)
- RELATED_TO            (fallback for weaker links)

Rules:
- Prefer specific identifiers (file paths, commit SHAs, ticket IDs)
- Entity names should be stable across documents (normalize "auth" vs "Auth Service")
- Relationships should carry intent, not just co-occurrence
- Keep descriptions concise (1 sentence)"""


CODE_EXTRACTION_PROMPT = """\
You are an expert at extracting a CONCEPTUAL knowledge graph from source code.
A separate deterministic pass already captures call/inherit/implement structure,
so DO NOT restate call edges. Extract the intent and architecture the code implies.

Return JSON with this structure:
{"entities": [...], "relationships": [...]}

Entity fields: name, entity_type, description
Relationship fields: source, target, rel_type, description, weight

Preferred entity types:
- module      (a file or package and its responsibility)
- component   (a cohesive unit: a service, client, store, parser)
- concept     (a domain idea the code implements: authentication, caching, retry)
- library     (external dependency imported/used)
- config      (settings, env vars, feature flags)

Preferred relationship types:
- IMPLEMENTS   (module/component -> concept)
- DEPENDS_ON   (module/component -> library/component)
- CONFIGURES   (module -> config)
- PART_OF      (module -> component; component -> system)
- RELATED_TO   (fallback for weaker links)

Rules:
- Extract meaning, not mechanics — concepts/responsibilities, not who-calls-whom.
- Entity names stable across files (normalize "auth" vs "Auth").
- Only what the code makes explicit (names, docstrings, imports, comments).
- Keep descriptions to one sentence."""


PROSE_EXTRACTION_PROMPT = """\
You are an expert at extracting knowledge graphs from everyday prose:
chat logs, reviews, bios, journals, emails, and social posts.

Return JSON with this structure:
{"entities": [...], "relationships": [...]}

Entity fields: name, entity_type, description
Relationship fields: source, target, rel_type, description, weight

Preferred entity types:
- person      (named people; use the fullest name seen)
- place       (cities, neighborhoods, venues)
- business    (restaurants, shops, brands)
- food        (dishes, cuisines, drinks)
- product     (things bought, used, recommended)
- activity    (hobbies, sports, events)

Preferred relationship types:
- LIVES_IN               (person -> place)
- LOCATED_IN             (business/venue -> place)
- LIKES / DISLIKES / PREFERS  (person -> food/product/activity/place)
- SERVES                 (business -> food/cuisine)
- VISITED                (person -> place/business)
- WORKS_AT               (person -> business)
- MARRIED_TO / FRIEND_OF / KNOWS  (person -> person)
- RECOMMENDS             (person -> business/product)
- RELATED_TO             (fallback for weaker links)

Rules:
- Common-noun objects are valid entities: "gumbo", "hot yoga", "oat-milk
  lattes". Do NOT require proper nouns.
- Name foods and dishes by their BASE form: "wood-fired margherita pizza"
  -> entity "pizza"; put the variant/preparation in the description. If a
  specific dish and its base differ meaningfully, emit both plus
  (dish) VARIANT_OF (base).
- Name places by their common full name ("New York City", not "NYC").
- Stated preferences and desires are facts. Map preference verbs onto the
  closed set: crave, love, enjoy, want, fancy -> LIKES; hate, can't stand,
  avoid -> DISLIKES; favor, would rather -> PREFERS. So "I've been craving
  pizza" -> (speaker) LIKES (pizza).
- In chat logs, resolve "I"/"me" to the named speaker; if the speaker
  cannot be identified, skip that relationship rather than guessing.
- In reviews, link the reviewed business to its location and to what it
  serves whenever the text states them.
- Use ONLY the relationship types listed above. If none fits exactly, use
  the closest listed type — never invent a new one.
- Only extract facts the text states or clearly implies.
- Normalize entity names (consistent casing); keep descriptions to one
  sentence."""


def get_prompt(name: str) -> str:
    """Get an extraction prompt by name."""
    if name == "dev":
        return DEV_EXTRACTION_PROMPT
    if name == "code":
        return CODE_EXTRACTION_PROMPT
    if name == "prose":
        return PROSE_EXTRACTION_PROMPT
    return EXTRACTION_SYSTEM_PROMPT


KNOWN_EXTRACTION_PROMPTS = ("default", "dev", "code", "prose")


def resolve_extraction_prompt(
    config,
    *,
    namespace: str | None = None,
    override: str | None = None,
    stamped: str | None = None,
) -> str:
    """Resolve the effective extraction prompt name for one document (#94).

    Precedence (first non-empty wins):
      1. ``override`` — the per-call ``extraction_prompt=`` kwarg on
         ``ingest()`` / ``ingest_records()``.
      2. ``stamped`` — ``documents.metadata['extraction_prompt']``, written
         at ingest time so deferred docs drain with the prompt they were
         ingested under, regardless of the drain worker's config.
      3. ``config.extraction_prompt_by_namespace[namespace]`` — the per-KB map.
      4. ``config.extraction_prompt`` — the process-global default.

    Unlike ``get_prompt`` (which silently falls back to the default prompt),
    an unknown name here raises ValueError: a typo in a per-call kwarg,
    stamped metadata, or the namespace map should fail loud, not silently
    extract with the wrong prompt.
    """
    ns_map = getattr(config, "extraction_prompt_by_namespace", None) or {}
    candidates = (
        ("extraction_prompt argument", override),
        ("document metadata 'extraction_prompt'", stamped),
        (
            f"extraction_prompt_by_namespace[{namespace!r}]",
            ns_map.get(namespace) if namespace is not None else None,
        ),
        ("config.extraction_prompt", getattr(config, "extraction_prompt", "default")),
    )
    for source, name in candidates:
        if not name:
            continue
        if name not in KNOWN_EXTRACTION_PROMPTS:
            raise ValueError(
                f"Unknown extraction prompt {name!r} (from {source}); "
                f"known prompts: {', '.join(KNOWN_EXTRACTION_PROMPTS)}"
            )
        return name
    return "default"


def config_with_prompt(config, prompt_name: str):
    """Return ``config`` with ``extraction_prompt`` set to ``prompt_name``.

    Every extractor reads the prompt from ``config.extraction_prompt``
    (they all share the ``(chunks, llm, db, config)`` seam — including the
    lede/union extractors, so a kwarg can't be threaded uniformly). A copied
    config is how a per-document prompt reaches ``extract_from_chunks``
    without mutating the shared process config.
    """
    if prompt_name == getattr(config, "extraction_prompt", "default"):
        return config
    return config.model_copy(update={"extraction_prompt": prompt_name})


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers (OpenAI-compatible API)."""

    async def complete(self, messages: list[dict]) -> str: ...

    async def complete_text(self, messages: list[dict], temperature: float = 0.2) -> str: ...


class HttpxLLMProvider:
    """OpenAI-compatible LLM provider via httpx.

    Reuses a single AsyncClient across calls so TCP connections are pooled
    instead of opened and closed for every LLM request. Call `aclose()` when
    done (GraphRAG.close() handles this automatically).
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", max_tokens: int = 0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        # max_tokens is sent on JSON-mode extraction calls when > 0. Local
        # OpenAI-compatible servers (e.g. mlx-lm) default to tiny completion
        # budgets (512) that silently truncate extraction JSON — the parse
        # then fails and the chunk yields an empty graph. See config
        # `llm_max_tokens`.
        self._max_tokens = max_tokens
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        # Pool up to 20 connections — enough for aggressive parallel ingestion
        # without overwhelming a local Ollama or a rate-limited API.
        self._client = httpx.AsyncClient(
            timeout=120,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        """Release the underlying connection pool."""
        await self._client.aclose()

    async def complete(self, messages: list[dict]) -> str:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        if self._max_tokens > 0:
            payload["max_tokens"] = self._max_tokens
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def complete_text(self, messages: list[dict], temperature: float = 0.2) -> str:
        """Complete a chat request for natural-language output (no JSON mode)."""
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json={
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def get_llm_provider(config: PGRGConfig) -> LLMProvider:
    """Factory to create LLM provider from config."""
    return HttpxLLMProvider(
        base_url=config.llm_base_url,
        model=config.llm_model,
        api_key=config.llm_api_key,
        max_tokens=getattr(config, "llm_max_tokens", 0),
    )


def _cache_key(chunk_content: str, prompt_name: str = "default") -> str:
    """Generate cache key for a chunk's extraction (prompt-aware)."""
    return hashlib.sha256(f"extract_v1:{prompt_name}:{chunk_content}".encode()).hexdigest()


def _is_insufficient_privilege(exc: Exception) -> bool:
    return getattr(exc, "sqlstate", None) == "42501"


async def _extract_single(
    chunk: dict,
    llm: LLMProvider,
    db,
    sem: asyncio.Semaphore,
    prompt_name: str = "default",
) -> ExtractionResult:
    """Extract entities/relationships from a single chunk (used in parallel)."""
    # Use embedded_content so the LLM sees the heading prefix when in hierarchy
    # strategy — the topic framing helps entity extraction. For auto strategy
    # this equals content. Falls back to content for rows produced before the
    # dual-field refactor.
    content = chunk.get("embedded_content") or chunk["content"]
    cache_k = _cache_key(content, prompt_name)

    # Check cache first (no semaphore needed — DB call is cheap)
    try:
        cached = await db.fetch_one(
            "SELECT response FROM pgrg_llm_cache WHERE key = %s",
            (cache_k,),
        )
    except Exception as e:
        if not _is_insufficient_privilege(e):
            raise
        logger.debug("LLM cache read skipped: %s", e)
        cached = None
    if cached:
        return filter_extraction(ExtractionResult.model_validate(cached["response"]))

    system_prompt = get_prompt(prompt_name)

    # Acquire semaphore before LLM call
    async with sem:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Extract entities and relationships from:\n\n{content}",
            },
        ]
        try:
            response_text = await llm.complete(messages)
            parsed = json.loads(response_text)
        except Exception as e:
            logger.warning(f"Extraction failed for chunk: {e}")
            return ExtractionResult()
        # Parse item-by-item so one malformed entity/relationship does not
        # discard the whole chunk's extraction (issue #69).
        result = _parse_extraction(parsed)

    # Cache non-empty results (outside semaphore)
    if result.entities or result.relationships:
        try:
            await db.execute(
                "INSERT INTO pgrg_llm_cache (key, response) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (cache_k, json.dumps(result.model_dump())),
            )
        except Exception as e:
            logger.debug("LLM cache write skipped: %s", e)

    return result


async def extract_from_chunks(
    chunks: list[dict],
    llm: LLMProvider,
    db,
    config: PGRGConfig,
) -> list[ExtractionResult]:
    """Extract entities and relationships from chunks in PARALLEL.

    Uses asyncio.gather with a semaphore to limit concurrent LLM calls.
    Caching prevents re-extraction of identical chunks.
    Respects config.extraction_prompt to pick between default and dev prompts.
    """
    import asyncio

    max_concurrent = getattr(config, "extract_concurrency", 8)
    sem = asyncio.Semaphore(max_concurrent)
    prompt_name = getattr(config, "extraction_prompt", "default")

    tasks = [_extract_single(chunk, llm, db, sem, prompt_name) for chunk in chunks]
    results = await asyncio.gather(*tasks)
    return list(results)
