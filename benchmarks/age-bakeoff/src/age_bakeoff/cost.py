"""Running USD tally for OpenAI calls with a hard budget ceiling."""
from __future__ import annotations


_PRICING: dict[str, tuple[float, float]] = {
    # (input $/1M tokens, output $/1M tokens)
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
_FALLBACK = (5.00, 15.00)


class CostBudgetExceeded(Exception):
    pass


class CostTracker:
    def __init__(self, budget_usd: float):
        self.budget_usd = budget_usd
        self.total_usd = 0.0
        self.calls: list[dict] = []

    def record(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        in_rate, out_rate = _PRICING.get(model, _FALLBACK)
        cost = (
            (prompt_tokens / 1_000_000) * in_rate
            + (completion_tokens / 1_000_000) * out_rate
        )
        self.total_usd += cost
        self.calls.append(
            {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "usd": cost,
            }
        )
        if self.total_usd > self.budget_usd:
            raise CostBudgetExceeded(
                f"Cost ${self.total_usd:.4f} exceeds budget ${self.budget_usd:.2f}"
            )
