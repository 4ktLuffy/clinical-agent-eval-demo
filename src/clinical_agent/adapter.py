"""Point the harness at someone else's agent.

An adapter is anything that turns (turn, context, tools) into a draft string. Two forms:

  openai:<model>       any OpenAI-compatible endpoint, via EVAL_MODEL_BASE_URL / _API_KEY
  python:pkg.mod:func  a callable in your own code, signature (turn, context, tools) -> str

The guardrail, rubric, intervals and mutation check do not know or care which was used.
That is the point of the split: this repository evaluates a deployment layer, and the agent
behind it is an argument.
"""

from __future__ import annotations

import importlib
import os
from typing import Callable, Protocol


class Adapter(Protocol):
    name: str

    def draft(self, turn: str, context: str, tools: dict) -> str:
        """One reply. Raise on failure; the caller decides whether to stop or escalate."""


class OpenAIAdapter:
    PROMPT = ("You are a clinical call handler. Answer the caller in two sentences, using "
              "only the context.\n\nContext:\n{context}\n\nCaller: {turn}\nAnswer:")

    def __init__(self, model: str) -> None:
        self.name = f"openai:{model}"
        self._model = model
        self._client = None

    def draft(self, turn: str, context: str, tools: dict) -> str:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(
                base_url=os.environ.get("EVAL_MODEL_BASE_URL", ""),
                api_key=os.environ.get("EVAL_MODEL_API_KEY", ""))
        response = self._client.chat.completions.create(
            model=self._model, temperature=0, max_tokens=400,
            messages=[{"role": "user",
                       "content": self.PROMPT.format(context=context or "none", turn=turn)}])
        return (response.choices[0].message.content or "").strip()


class CallableAdapter:
    def __init__(self, target: str) -> None:
        module_name, _, attribute = target.partition(":")
        if not attribute:
            raise ValueError("python adapters are written as python:package.module:function")
        self.name = f"python:{target}"
        self._fn: Callable[[str, str, dict], str] = getattr(
            importlib.import_module(module_name), attribute)

    def draft(self, turn: str, context: str, tools: dict) -> str:
        return str(self._fn(turn, context, tools))


def build_adapter(spec: str):
    """`spec` is "mock", "openai:<model>", or "python:module:function"."""
    if not spec or spec == "mock":
        return None
    if spec.startswith("openai:"):
        return OpenAIAdapter(spec[len("openai:"):])
    if spec.startswith("python:"):
        return CallableAdapter(spec[len("python:"):])
    raise ValueError(f"unknown adapter {spec!r}; expected mock, openai:<model>, "
                     "or python:module:function")
