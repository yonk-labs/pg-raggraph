"""Entity/relationship extraction using LLM (OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Protocol, runtime_checkable

import httpx

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import ExtractionResult

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


def get_prompt(name: str) -> str:
    """Get an extraction prompt by name."""
    if name == "dev":
        return DEV_EXTRACTION_PROMPT
    return EXTRACTION_SYSTEM_PROMPT


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

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self._base_url = base_url.rstrip("/")
        self._model = model
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
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json={
                "model": self._model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            },
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
    )


def _cache_key(chunk_content: str, prompt_name: str = "default") -> str:
    """Generate cache key for a chunk's extraction (prompt-aware)."""
    return hashlib.sha256(f"extract_v1:{prompt_name}:{chunk_content}".encode()).hexdigest()


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
    cached = await db.fetch_one("SELECT response FROM pgrg_llm_cache WHERE key = %s", (cache_k,))
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
            result = ExtractionResult.model_validate(parsed)
            result = filter_extraction(result)
        except Exception as e:
            logger.warning(f"Extraction failed for chunk: {e}")
            return ExtractionResult()

    # Cache non-empty results (outside semaphore)
    if result.entities or result.relationships:
        try:
            await db.execute(
                "INSERT INTO pgrg_llm_cache (key, response) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (cache_k, json.dumps(result.model_dump())),
            )
        except Exception as e:
            logger.debug("LLM cache write failed: %s", e)

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
