"""Call accounting and rate-limit handling for the real-model path.

Two rules, both deliberate:

  A 429 stops the run. It is not retried, not backed off into, not slept through. A free
  tier that has said no is not a transient error, and hammering it is how an account gets
  suspended. The run stops, reports what it completed, and marks the result partial.

  A hard call cap stops the run before the provider has to. `--max-calls` is the ceiling
  on total model calls in one run, so a loop bug cannot spend an entire quota.

Both outcomes produce a report; neither produces a silent truncation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExhausted(Exception):
    """The configured call cap was reached."""


class RateLimited(Exception):
    """The provider returned 429. Deliberately not retried."""


@dataclass
class CallBudget:
    max_calls: int = 2000
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stopped_reason: str | None = None
    per_model: dict[str, int] = field(default_factory=dict)

    def spend(self, model: str) -> None:
        if self.calls >= self.max_calls:
            self.stopped_reason = f"call cap reached ({self.max_calls})"
            raise BudgetExhausted(self.stopped_reason)
        self.calls += 1
        self.per_model[model] = self.per_model.get(model, 0) + 1

    def record_usage(self, usage: object) -> None:
        """Record token usage when the provider reports it. Absent on some endpoints."""
        if usage is None:
            return
        self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

    def note_rate_limit(self, model: str) -> None:
        self.stopped_reason = f"provider rate-limited {model} (HTTP 429); run stopped, not retried"

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "max_calls": self.max_calls,
            "per_model": dict(self.per_model),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "stopped_reason": self.stopped_reason,
        }


def is_rate_limit(exc: Exception) -> bool:
    """True for a 429 from either SDK, without importing either of them."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "429" in str(exc)[:200]
