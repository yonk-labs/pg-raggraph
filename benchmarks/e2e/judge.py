"""LLM-as-judge — gpt-5-mini primary, local Qwen fallback.

The judge does two things in one call: (1) answer the question from the
retrieved context, (2) grade that answer against the reference answers.
This matches the findings-doc methodology (self-grading; internally
consistent across cells, slightly lenient vs a separate judge).

Disk-cached by (question, top_k_hash, reference_hash). Re-runs against
the same cell are free.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

CACHE_ROOT = Path(
    os.environ.get(
        "PGRG_BENCH_JUDGE_CACHE",
        str(Path.home() / ".cache" / "pg_raggraph_bench" / "judge"),
    )
)


@dataclass
class JudgeResult:
    score: float  # 1.0 correct, 0.5 partial, 0.0 wrong
    answer: str
    reason: str
    provider: str


JUDGE_PROMPT = """You are grading a retrieval system's answer to a multi-hop question.

Question: {question}

Retrieved context (top {n_chunks} chunks):
{context}

Reference answer(s): {reference}

Your job:
1. Read the context.
2. Try to answer the question using ONLY the context.
3. Compare your answer to the reference.

Respond with strict JSON only (no markdown, no commentary):
{{"answer": "<your answer in <= 25 words>", "score": <1.0|0.5|0.0>, "reason": "<one short sentence>"}}

Scoring:
- 1.0: your answer matches the reference (semantic match, not just lexical)
- 0.5: partial — captures the key entity but misses a hop, OR matches one of several references
- 0.0: wrong or "insufficient information" when reference IS in context

If the reference says "Insufficient information" and your answer also says it cannot be answered, score 1.0."""


def _cache_key(question: str, chunks: list[str], reference: list[str], model: str) -> str:
    payload = json.dumps(
        {"q": question, "c": chunks, "r": reference, "m": model},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return CACHE_ROOT / f"{key}.json"


def _cache_get(key: str) -> JudgeResult | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        return JudgeResult(**d)
    except Exception:
        return None


def _cache_put(key: str, r: JudgeResult) -> None:
    _cache_path(key).write_text(
        json.dumps(
            {"score": r.score, "answer": r.answer, "reason": r.reason, "provider": r.provider}
        )
    )


class Judge:
    """OpenAI-compatible HTTP client for the judge call.

    Provider selection:
    - judge="openai"  → require OPENAI_API_KEY; use gpt-5-mini
    - judge="local"   → use PGRG_BENCH_LOCAL_LLM_BASE / MODEL (Qwen vLLM)
    - judge="auto"    → openai if key present, else local
    """

    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.provider_name, self.base_url, self.model, self.api_key = self._resolve(mode)

    def _resolve(self, mode: str) -> tuple[str, str, str, str]:
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        local_base = os.environ.get("PGRG_BENCH_LOCAL_LLM_BASE", "http://localhost:8000/v1")
        local_model = os.environ.get("PGRG_BENCH_LOCAL_LLM_MODEL", "Qwen/Qwen3-Coder-30B")
        if mode == "openai":
            if not openai_key:
                raise RuntimeError("judge=openai but OPENAI_API_KEY not set")
            return ("openai:gpt-5-mini", "https://api.openai.com/v1", "gpt-5-mini", openai_key)
        if mode == "local":
            return (f"local:{local_model}", local_base, local_model, "EMPTY")
        # auto
        if openai_key:
            return ("openai:gpt-5-mini", "https://api.openai.com/v1", "gpt-5-mini", openai_key)
        return (f"local:{local_model}", local_base, local_model, "EMPTY")

    async def judge(
        self,
        *,
        question: str,
        context_chunks: list[str],
        reference_answers: list[str],
    ) -> JudgeResult:
        cache_id = _cache_key(question, context_chunks, reference_answers, self.model)
        cached = _cache_get(cache_id)
        if cached is not None:
            return cached

        context = "\n\n---\n\n".join(
            f"[Chunk {i + 1}]\n{c[:1500]}" for i, c in enumerate(context_chunks)
        )
        prompt = JUDGE_PROMPT.format(
            question=question,
            n_chunks=len(context_chunks),
            context=context,
            reference=" || ".join(reference_answers),
        )
        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.model.startswith("gpt-5"):
            # gpt-5 family only supports default temperature (1.0); use
            # reasoning_effort=minimal to keep the call short and cheap.
            body["reasoning_effort"] = "minimal"
        else:
            body["temperature"] = 0.0
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"]
        result = _parse_judge_response(text, self.provider_name)
        _cache_put(cache_id, result)
        return result


def _parse_judge_response(text: str, provider: str) -> JudgeResult:
    """Lenient JSON parse — strip markdown fences if the model added them."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        d = json.loads(raw)
    except Exception:
        # Try to extract the first {...} block.
        import re

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
            except Exception:
                d = {}
        else:
            d = {}

    score = d.get("score")
    if score is None:
        return JudgeResult(score=0.0, answer=raw[:200], reason="unparseable", provider=provider)
    try:
        score_f = float(score)
    except Exception:
        score_f = 0.0
    return JudgeResult(
        score=max(0.0, min(1.0, score_f)),
        answer=str(d.get("answer", ""))[:500],
        reason=str(d.get("reason", ""))[:500],
        provider=provider,
    )
