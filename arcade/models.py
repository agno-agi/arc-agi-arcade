"""
Models
======
Provider model classes that report every response's token usage to the game's meter (so traces carry
cumulative token stamps — the raw material for score-vs-token curves).
"""

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from agno.metrics import MessageMetrics
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.fireworks import Fireworks
from agno.models.google import Gemini
from agno.models.mistral import MistralChat
from agno.models.openai import OpenAIResponses
from agno.models.xai import xAI

from arcade.instructions import EXTRACT_PROMPT
from arcade.tools import ArcadeTools


@dataclass
class Metered:
    """Mixed into a provider model class: reports every response's usage to the game's meter."""

    meter: Callable[[MessageMetrics], None] | None = None

    def _get_metrics(self, response_usage: Any) -> MessageMetrics:
        metrics = super()._get_metrics(response_usage)  # type: ignore[misc]
        if self.meter is not None:
            self.meter(metrics)
        return metrics


@dataclass
class MeteredFireworks(Metered, Fireworks): ...


@dataclass
class MeteredClaude(Metered, Claude): ...


@dataclass
class MeteredGemini(Metered, Gemini): ...


@dataclass
class MeteredDeepSeek(Metered, DeepSeek): ...


@dataclass
class MeteredXAI(Metered, xAI): ...


@dataclass
class MeteredMistral(Metered, MistralChat): ...


@dataclass
class MeteredResponses(Metered, OpenAIResponses): ...


def _no_effort(model: str, effort: str | None) -> None:
    if effort is not None:
        raise RuntimeError(f"effort is not configurable for {model} (supported on gpt-*, claude*, gemini-*)")


def get_model(model: str, meter: Callable[[MessageMetrics], None], effort: str | None = None) -> Any:
    """The playing model for a model id, wired to the meter. effort overrides the lane's default reasoning
    depth (claude: low/medium/high/xhigh/max, default max; gpt: minimal..max, default max; gemini:
    low/high, default high); lanes without the knob refuse it loudly rather than silently ignore it."""

    if model.startswith("accounts/fireworks/"):
        _no_effort(model, effort)
        # The open-weight lanes: single-vendor OpenAI-compatible serving with accurate usage objects.
        # (Aggregator routing is deliberately unsupported: backend roulette breaks benchmark comparability)
        return MeteredFireworks(
            id=model,
            meter=meter,
            max_tokens=16_000,
            # Chat-completions passthrough: commit one action at a time, same as the other lanes.
            request_params={"parallel_tool_calls": False},
        )
    if model.startswith("claude"):
        # The Claude lane: native effort via output_config, thinking off, explicit prompt caching.
        return MeteredClaude(
            id=model,
            meter=meter,
            max_tokens=24_000,
            output_config={"effort": effort or "max"},
            cache_system_prompt=True,
            cache_tools=True,
        )
    if model.startswith("gemini-"):
        # The Gemini lane: thinking at the highest level, usage metered like every other lane.
        return MeteredGemini(id=model, meter=meter, thinking_level=effort or "high")
    if model.startswith("deepseek-"):
        _no_effort(model, effort)
        # First-party DeepSeek: OpenAI-compatible chat, one action at a time.
        return MeteredDeepSeek(id=model, meter=meter, max_tokens=8_000, request_params={"parallel_tool_calls": False})
    if model.startswith("grok-"):
        _no_effort(model, effort)
        return MeteredXAI(id=model, meter=meter, max_tokens=16_000, request_params={"parallel_tool_calls": False})
    if model.startswith("mistral-") or model.startswith("magistral-"):
        _no_effort(model, effort)
        return MeteredMistral(id=model, meter=meter, max_tokens=8_000)
    if model.startswith("gpt-"):
        return MeteredResponses(
            id=model,
            meter=meter,
            reasoning_effort=effort or "max",  # type: ignore[arg-type]
            parallel_tool_calls=False,
            truncation="auto",
            service_tier="flex",
        )
    raise RuntimeError(
        f"unknown model id: {model} "
        "(expected gpt-*, claude*, gemini-*, deepseek-*, grok-*, mistral-*, or accounts/fireworks/*)"
    )


def episode_extractor(game: ArcadeTools, model: str) -> Callable[[str, str], str]:
    """One distillation call per session end, with the player's own provider, metered into the game's
    token ledger. Low effort: the job is summarization of evidence already gathered, not play.
    Clients are built lazily inside the call so agent creation never needs the provider reachable."""

    def chat_extractor(base_url: str | None, key_env: str | None) -> Callable[[str, str], str]:
        def extract(transcript: str, manual: str) -> str:
            from os import environ

            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=environ.get(key_env) if key_env else None)
            response = client.chat.completions.create(
                model=model,
                max_tokens=2_000,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACT_PROMPT.format(manual=manual or "(empty)", transcript=transcript),
                    }
                ],
            )
            usage = response.usage
            if usage is not None:
                game.meter(
                    SimpleNamespace(
                        input_tokens=usage.prompt_tokens or 0,
                        output_tokens=usage.completion_tokens or 0,
                        total_tokens=usage.total_tokens or 0,
                        cache_read_tokens=getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
                        or 0,
                        reasoning_tokens=0,
                    )
                )
            return response.choices[0].message.content or "" if response.choices else ""

        return extract

    def extract_claude(transcript: str, manual: str) -> str:
        from anthropic import Anthropic

        response = Anthropic().messages.create(
            model=model,
            max_tokens=2_000,
            messages=[
                {"role": "user", "content": EXTRACT_PROMPT.format(manual=manual or "(empty)", transcript=transcript)}
            ],
        )
        usage = response.usage
        game.meter(
            SimpleNamespace(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                total_tokens=(usage.input_tokens or 0) + (usage.output_tokens or 0),
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                reasoning_tokens=0,
            )
        )
        return "".join(getattr(block, "text", "") for block in response.content)

    def extract_gpt(transcript: str, manual: str) -> str:
        from openai import OpenAI

        response = OpenAI().responses.create(
            model=model,
            input=EXTRACT_PROMPT.format(manual=manual or "(empty)", transcript=transcript),
        )
        usage = response.usage
        if usage is not None:
            game.meter(
                SimpleNamespace(
                    input_tokens=usage.input_tokens or 0,
                    output_tokens=usage.output_tokens or 0,
                    total_tokens=usage.total_tokens or 0,
                    cache_read_tokens=getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0),
                    reasoning_tokens=getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0),
                )
            )
        return response.output_text or ""

    if model.startswith("accounts/fireworks/"):
        return chat_extractor("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY")
    if model.startswith("deepseek-"):
        return chat_extractor("https://api.deepseek.com", "DEEPSEEK_API_KEY")
    if model.startswith("grok-"):
        return chat_extractor("https://api.x.ai/v1", "XAI_API_KEY")
    if model.startswith("mistral-") or model.startswith("magistral-"):
        return chat_extractor("https://api.mistral.ai/v1", "MISTRAL_API_KEY")

    def extract_gemini(transcript: str, manual: str) -> str:
        from google import genai

        response = genai.Client().models.generate_content(
            model=model, contents=EXTRACT_PROMPT.format(manual=manual or "(empty)", transcript=transcript)
        )
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            game.meter(
                SimpleNamespace(
                    input_tokens=usage.prompt_token_count or 0,
                    output_tokens=usage.candidates_token_count or 0,
                    total_tokens=usage.total_token_count or 0,
                    cache_read_tokens=getattr(usage, "cached_content_token_count", 0) or 0,
                    reasoning_tokens=getattr(usage, "thoughts_token_count", 0) or 0,
                )
            )
        return response.text or ""

    if model.startswith("gemini-"):
        return extract_gemini
    if model.startswith("claude"):
        return extract_claude
    if model.startswith("gpt-"):
        return extract_gpt
    raise RuntimeError(
        f"unknown model id: {model} "
        "(expected gpt-*, claude*, gemini-*, deepseek-*, grok-*, mistral-*, or accounts/fireworks/*)"
    )
