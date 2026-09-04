"""The one seam between the offline path and the real-model path.

Everything downstream of this file -- retrieval, tools, guardrail, scoring -- is the
same code in both modes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from clinical_agent.budget import CallBudget, RateLimited, is_rate_limit

DEFAULT_MODEL = "claude-opus-5"

# Provider selection. EVAL_MODEL is "<provider>:<model>":
#
#   anthropic:claude-opus-5
#   openai-compatible:google/gemini-2.0-flash-exp:free
#
# The second form covers OpenRouter, Gemini's OpenAI-compatible endpoint, vLLM, LM Studio,
# and anything else speaking the OpenAI chat API, via EVAL_MODEL_BASE_URL. The key is read
# from EVAL_MODEL_API_KEY (or ANTHROPIC_API_KEY for the anthropic provider) and is never
# printed, logged, or written to a report -- tests/test_no_key_leak.py enforces that.
ENV_MODEL = "EVAL_MODEL"
ENV_BASE_URL = "EVAL_MODEL_BASE_URL"
ENV_API_KEY = "EVAL_MODEL_API_KEY"


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Split "<provider>:<model>" into (provider, model).

    Model names legitimately contain colons (``google/gemini-2.0-flash-exp:free``), so only
    the first colon separates. A bare name with no known provider prefix means anthropic,
    which is what the earlier CLINICAL_AGENT_MODEL meant.
    """
    provider, _, model = spec.partition(":")
    if provider in ("anthropic", "openai-compatible") and model:
        return provider, model
    return "anthropic", spec


@dataclass(frozen=True)
class Draft:
    text: str
    model: str


class LLMClient(Protocol):
    name: str

    def complete(self, turn_id: str, prompt: str) -> Draft: ...


class MockClient:
    """Returns scripted drafts keyed by turn id.

    Some scripts are deliberately unsafe, so the guardrail has real work to do and the
    mutation check has something to catch.
    """

    name = "mock"

    def __init__(self, scripts: dict[str, str]) -> None:
        self._scripts = dict(scripts)

    def complete(self, turn_id: str, prompt: str) -> Draft:
        if turn_id not in self._scripts:
            raise KeyError(f"no mock draft scripted for turn {turn_id}")
        return Draft(text=self._scripts[turn_id], model=self.name)


class AnthropicClient:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get(ENV_API_KEY)):
            raise RuntimeError(
                f"neither ANTHROPIC_API_KEY nor {ENV_API_KEY} is set; real mode needs a key"
            )
        self.name = model
        self._model = model
        self._client = None
        self.budget = CallBudget()

    def complete(self, turn_id: str, prompt: str) -> Draft:
        self.budget.spend(self._model)
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ[ENV_API_KEY]
            )
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            if is_rate_limit(exc):
                self.budget.note_rate_limit(self._model)
                raise RateLimited(self.budget.stopped_reason) from exc
            raise
        self.budget.record_usage(getattr(message, "usage", None))
        text = "".join(block.text for block in message.content if block.type == "text")
        return Draft(text=text.strip(), model=self._model)


class OpenAICompatibleClient:
    """Any endpoint speaking the OpenAI chat API: OpenRouter, Gemini, vLLM, LM Studio."""

    def __init__(self, model: str, base_url: str, api_key: str,
                 budget: CallBudget | None = None) -> None:
        if not base_url:
            raise RuntimeError(
                f"{ENV_BASE_URL} must be set for the openai-compatible provider "
                "(e.g. https://openrouter.ai/api/v1)"
            )
        if not api_key:
            raise RuntimeError(f"{ENV_API_KEY} is not set; real mode needs a key")
        self.name = model
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._client = None
        self.budget = budget or CallBudget()

    def complete(self, turn_id: str, prompt: str) -> Draft:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(base_url=self._base_url, api_key=self._api_key)
        self.budget.spend(self._model)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            if is_rate_limit(exc):
                self.budget.note_rate_limit(self._model)
                raise RateLimited(self.budget.stopped_reason) from exc
            raise
        self.budget.record_usage(getattr(response, "usage", None))
        return Draft(text=(response.choices[0].message.content or "").strip(), model=self._model)


def build_client(mode: str, scripts: dict[str, str]) -> LLMClient:
    if mode == "mock":
        return MockClient(scripts)
    if mode != "real":
        raise ValueError(f"unknown mode {mode!r}; expected 'mock' or 'real'")

    spec = os.environ.get(ENV_MODEL) or os.environ.get("CLINICAL_AGENT_MODEL", DEFAULT_MODEL)
    provider, model = parse_model_spec(spec)
    if provider == "openai-compatible":
        return OpenAICompatibleClient(
            model,
            os.environ.get(ENV_BASE_URL, ""),
            os.environ.get(ENV_API_KEY, ""),
        )
    return AnthropicClient(model)
