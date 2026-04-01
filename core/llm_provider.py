"""LLM provider factory and clients for Brain roles (evaluator, contract verifier).

Supports Anthropic Messages API, OpenAI Chat Completions, and OpenAI-compatible
servers (DeepSeek, Groq, Ollama) via ``base_url``.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Any, Optional

# --- Optional SDKs (same pattern as evaluator.py) ---
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


def extract_anthropic_message_text(message: object) -> str:
    """Extract plain text from an Anthropic Messages API response."""
    blocks = getattr(message, "content", None)
    if not blocks:
        return ""
    for block in blocks:
        if getattr(block, "type", None) == "text":
            t = getattr(block, "text", None)
            if t is not None:
                return str(t)
    try:
        first = blocks[0]
        t = getattr(first, "text", None)
        if t is not None:
            return str(t)
    except (IndexError, TypeError, AttributeError):
        pass
    return ""


def extract_openai_completion_text(response: object) -> str:
    """Extract assistant text from an OpenAI Chat Completions response."""
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    msg = getattr(choices[0], "message", None)
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                t = part.get("text")
                if t:
                    parts.append(str(t))
            else:
                t = getattr(part, "text", None)
                if t is not None:
                    parts.append(str(t))
        return "".join(parts)
    return str(content)


class VisionBridge:
    """Normalize Playwright PNG screenshots for different provider image payloads.

    Anthropic expects base64 in a structured ``source`` block; OpenAI-compatible
    APIs expect a data URL (or URL) in ``image_url.url``.
    """

    @staticmethod
    def png_bytes_to_anthropic_image_block(png_bytes: bytes) -> dict[str, Any]:
        """Anthropic Messages API image block (base64 source)."""
        b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        }

    @staticmethod
    def png_bytes_to_openai_data_url(png_bytes: bytes) -> str:
        """RFC 2397 data URL for OpenAI ``image_url`` content parts."""
        b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"


class BaseLLMClient(ABC):
    """Unified interface for Brain API calls (text and vision)."""

    @abstractmethod
    def complete_text(self, model: str, user_text: str, *, max_tokens: int) -> str:
        """Single user message, text-only."""

    @abstractmethod
    def complete_text_with_vision_png(
        self,
        model: str,
        *,
        png_bytes: bytes,
        text_prompt: str,
        max_tokens: int,
    ) -> str:
        """User message with one PNG image and a text rubric."""


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Messages API."""

    def __init__(self) -> None:
        if anthropic is None:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        self._client = anthropic.Anthropic()

    def complete_text(self, model: str, user_text: str, *, max_tokens: int) -> str:
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user_text}],
        )
        return extract_anthropic_message_text(message)

    def complete_text_with_vision_png(
        self,
        model: str,
        *,
        png_bytes: bytes,
        text_prompt: str,
        max_tokens: int,
    ) -> str:
        image_block = VisionBridge.png_bytes_to_anthropic_image_block(png_bytes)
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": text_prompt},
                    ],
                }
            ],
        )
        return extract_anthropic_message_text(message)


class OpenAILLMClient(BaseLLMClient):
    """OpenAI Chat Completions or compatible servers (``base_url`` for DeepSeek / Ollama)."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        kwargs: dict[str, Any] = {}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def complete_text(self, model: str, user_text: str, *, max_tokens: int) -> str:
        response = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user_text}],
        )
        return extract_openai_completion_text(response)

    def complete_text_with_vision_png(
        self,
        model: str,
        *,
        png_bytes: bytes,
        text_prompt: str,
        max_tokens: int,
    ) -> str:
        data_url = VisionBridge.png_bytes_to_openai_data_url(png_bytes)
        response = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
        )
        return extract_openai_completion_text(response)


def _normalize_provider_id(provider: str) -> str:
    return (provider or "").strip().lower().replace("_", "-")


class LLMProviderFactory:
    """Construct a ``BaseLLMClient`` from harness ``provider`` and optional ``base_url``."""

    @staticmethod
    def create(provider: str, *, base_url: Optional[str] = None) -> BaseLLMClient:
        pid = _normalize_provider_id(provider)
        if not pid or pid == "anthropic":
            return AnthropicLLMClient()
        if pid == "openai":
            return OpenAILLMClient(base_url=None)
        if pid == "openai-compatible":
            if not base_url or not str(base_url).strip():
                raise ValueError(
                    "provider 'openai-compatible' requires a non-empty base_url "
                    "(e.g. https://api.deepseek.com or http://localhost:11434/v1)"
                )
            return OpenAILLMClient(base_url=str(base_url).strip())
        raise ValueError(
            f"Unknown LLM provider {provider!r}. "
            "Use: anthropic, openai, or openai-compatible."
        )


def brain_client_for_role(models: Optional[dict[str, str]], role: str) -> BaseLLMClient:
    """Resolve provider and base_url from ``HarnessConfig.models`` for a Brain role."""
    m = models or {}
    provider = m.get(f"{role}_provider") or "anthropic"
    raw_url = m.get(f"{role}_base_url")
    base_url = str(raw_url).strip() if raw_url else None
    return LLMProviderFactory.create(provider, base_url=base_url)
