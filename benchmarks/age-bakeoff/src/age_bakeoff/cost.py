"""Running USD tally for OpenAI calls with a hard budget ceiling."""
from __future__ import annotations


_PRICING: dict[str, tuple[float, float]] = {
    # (input $/1M tokens, output $/1M tokens)
    # GPT-5 family (per user-provided pricing 2026-04-21)
    "gpt-5": (1.25, 5.00),
    "gpt-5.1": (1.25, 5.00),
    "gpt-5-mini": (0.25, 1.00),
    "gpt-5-nano": (0.125, 0.50),
    "gpt-5.4": (2.50, 10.00),
    "gpt-5.4-mini": (0.75, 3.00),
    "gpt-5.4-nano": (0.375, 1.50),
    # Legacy
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-mini-2025-04-14": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
# Local models run at $0. Any model name hitting the local prefix list
# or containing a "Qwen" / "qwen" substring is zero-priced.
_LOCAL_PREFIXES = ("Intel/", "Qwen/", "ollama/", "local/")
_LOCAL_SUBSTRINGS = ("qwen", "llama", "mistral", "phi-")
_FALLBACK = (5.00, 15.00)


def _is_local_model(model: str) -> bool:
    if model.startswith(_LOCAL_PREFIXES):
        return True
    low = model.lower()
    return any(s in low for s in _LOCAL_SUBSTRINGS)


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
        if _is_local_model(model):
            in_rate, out_rate = (0.0, 0.0)
        else:
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

    def tally_report(self) -> dict:
        by_model: dict[str, dict] = {}
        for call in self.calls:
            m = call["model"]
            bucket = by_model.setdefault(m, {"calls": 0, "usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
            bucket["calls"] += 1
            bucket["usd"] += call["usd"]
            bucket["prompt_tokens"] += call["prompt_tokens"]
            bucket["completion_tokens"] += call["completion_tokens"]
        return {
            "total_usd": self.total_usd,
            "budget_usd": self.budget_usd,
            "by_model": by_model,
        }

    def save_report(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps(self.tally_report(), indent=2, sort_keys=True))


def load_tally_reports(results_dir) -> dict:
    """Aggregate per-command cost files into a combined view.

    Reads every ``cost-*.json`` file in ``results_dir`` (e.g. ``cost-run.json``,
    ``cost-judge.json``, ``cost-diagnose.json``) and returns a merged tally so
    SC-015's $50 budget can be checked across command sequences.

    Returns: ``{total_usd, budget_usd, by_command: {name: {total_usd, by_model}},
    by_model: {...}}``.
    """
    import json
    from pathlib import Path

    results_dir = Path(results_dir)
    combined: dict = {
        "total_usd": 0.0,
        "budget_usd": None,
        "by_command": {},
        "by_model": {},
    }
    for path in sorted(results_dir.glob("cost-*.json")):
        command = path.stem.replace("cost-", "", 1)  # "cost-run" -> "run"
        data = json.loads(path.read_text())
        combined["by_command"][command] = {
            "total_usd": data.get("total_usd", 0.0),
            "by_model": data.get("by_model", {}),
        }
        combined["total_usd"] += data.get("total_usd", 0.0)
        if combined["budget_usd"] is None and data.get("budget_usd"):
            combined["budget_usd"] = data["budget_usd"]
        for model, bucket in data.get("by_model", {}).items():
            agg = combined["by_model"].setdefault(
                model,
                {"calls": 0, "usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            for k in ("calls", "usd", "prompt_tokens", "completion_tokens"):
                agg[k] += bucket.get(k, 0)
    return combined
