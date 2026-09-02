"""The one seam between the offline path and the real-model path.

Everything downstream of this file -- retrieval, tools, guardrail, scoring -- is the
same code in both modes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MODEL = "claude-opus-5"


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
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set; real mode needs a key")
        self.name = model
        self._model = model
        self._client = None

    def complete(self, turn_id: str, prompt: str) -> Draft:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        message = self._client.messages.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return Draft(text=text.strip(), model=self._model)


def build_client(mode: str, scripts: dict[str, str]) -> LLMClient:
    if mode == "mock":
        return MockClient(scripts)
    if mode == "real":
        return AnthropicClient(os.environ.get("CLINICAL_AGENT_MODEL", DEFAULT_MODEL))
    raise ValueError(f"unknown mode {mode!r}; expected 'mock' or 'real'")
