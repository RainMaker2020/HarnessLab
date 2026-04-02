"""LLM provider factory and clients for Brain roles (evaluator, contract verifier).

Supports Anthropic Messages API, OpenAI Chat Completions, and OpenAI-compatible
servers (DeepSeek, Groq, Ollama) via ``base_url``.

OpenAI-compatible HTTP APIs disagree on completion-budget fields: some expect
``max_tokens``, others ``max_completion_tokens`` (notably reasoning models).
:class:`OpenAILLMClient` sends one at a time and retries with the alternate name
when the server rejects the first (see ``_chat_completions_create_with_token_budget``).
"""

from __future__ import annotations

import base64
import os
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


def _flatten_openai_error_message(exc: BaseException) -> str:
    """Collect human-readable text from OpenAI SDK errors for heuristics."""
    parts: list[str] = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))
    resp = getattr(exc, "response", None)
    if resp is not None:
        text = getattr(resp, "text", None)
        if text:
            parts.append(str(text))
    return " ".join(parts).lower()


def _is_retryable_token_limit_error(exc: BaseException) -> bool:
    """True if retrying with the alternate token-budget parameter may help.

    OpenAI reasoning models and some third-party APIs accept ``max_completion_tokens``
    but reject ``max_tokens`` (or the reverse). DeepSeek/Groq/Ollama compatibility
    varies; we only retry on errors that look parameter-related, not auth/rate limits.
    """
    status = getattr(exc, "status_code", None)
    if status == 401 or status == 403:
        return False
    if status == 429:
        return False
    if status is not None and status >= 500:
        return False

    if isinstance(exc, TypeError):
        msg = str(exc).lower()
        return "max_token" in msg or "unexpected keyword" in msg

    if status is not None and status not in (400, 404, 422):
        return False

    msg = _flatten_openai_error_message(exc)
    if not msg.strip():
        return False

    if any(
        h in msg
        for h in (
            "max_tokens",
            "max_completion_tokens",
            "completion_tokens",
            "reasoning",
        )
    ):
        return True
    if "unsupported" in msg or "unknown parameter" in msg or "not supported" in msg:
        return True
    if "invalid" in msg and ("parameter" in msg or "field" in msg):
        return True
    return False


def _chat_completions_create_with_token_budget(
    client: Any,
    *,
    model: str,
    messages: list,
    max_tokens: int,
) -> Any:
    """Call ``chat.completions.create`` with a completion budget; alternate param on failure.

    Tries ``max_tokens`` first (widest OpenAI-compatible behavior). If the server
    rejects that parameter (common for reasoning-only endpoints), retries with
    ``max_completion_tokens`` only. Does not send both keys in one request.
    """
    create = client.chat.completions.create
    attempts: tuple[tuple[str, int], ...] = (
        ("max_tokens", max_tokens),
        ("max_completion_tokens", max_tokens),
    )
    for key, value in attempts:
        try:
            kwargs = {key: value}
            return create(model=model, messages=messages, **kwargs)
        except Exception as exc:
            if key == attempts[-1][0] or not _is_retryable_token_limit_error(exc):
                raise
    raise RuntimeError("unreachable: token budget attempts exhausted")  # pragma: no cover


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


def _first_non_empty_env(*keys: str) -> Optional[str]:
    for key in keys:
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


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
        key = _first_non_empty_env("ANTHROPIC_API_KEY")
        kwargs: dict[str, Any] = {}
        if key:
            kwargs["api_key"] = key
        self._client = anthropic.Anthropic(**kwargs)

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

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
    ) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        kwargs: dict[str, Any] = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key is not None and str(api_key).strip():
            kwargs["api_key"] = str(api_key).strip()
        self._client = OpenAI(**kwargs)

    def complete_text(self, model: str, user_text: str, *, max_tokens: int) -> str:
        response = _chat_completions_create_with_token_budget(
            self._client,
            model=model,
            messages=[{"role": "user", "content": user_text}],
            max_tokens=max_tokens,
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
        response = _chat_completions_create_with_token_budget(
            self._client,
            model=model,
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
            max_tokens=max_tokens,
        )
        return extract_openai_completion_text(response)


def _normalize_provider_id(provider: str) -> str:
    return (provider or "").strip().lower().replace("_", "-")


def _resolve_openai_api_key(provider: str, base_url: Optional[str]) -> Optional[str]:
    """API key for :class:`OpenAI` client: prefer role-specific .env vars for multi-provider setups.

    - ``openai`` → ``OPENAI_API_KEY``
    - ``openai-compatible`` with DeepSeek host → ``DEEPSEEK_API_KEY``, then ``OPENAI_API_KEY``
    - other compatible servers → ``OPENAI_COMPATIBLE_API_KEY``, then ``OPENAI_API_KEY``

    Returns ``None`` when no env key is set so the SDK uses its default (typically
    ``OPENAI_API_KEY`` for the default endpoint).

    DeepSeek routing uses a substring check (``\"deepseek\" in base_url``) for the
    official API host. Custom proxies without that substring use the generic
    compatible key chain; set ``OPENAI_COMPATIBLE_API_KEY`` or ``OPENAI_API_KEY``.
    """
    pid = _normalize_provider_id(provider)
    bu = (base_url or "").lower()
    if pid == "openai":
        return _first_non_empty_env("OPENAI_API_KEY")
    if pid == "openai-compatible":
        # Hostname heuristic — see docstring if your DeepSeek proxy URL lacks "deepseek".
        if "deepseek" in bu:
            return _first_non_empty_env("DEEPSEEK_API_KEY", "OPENAI_API_KEY")
        return _first_non_empty_env("OPENAI_COMPATIBLE_API_KEY", "OPENAI_API_KEY")
    return None


class LLMProviderFactory:
    """Construct a ``BaseLLMClient`` from harness ``provider`` and optional ``base_url``."""

    @staticmethod
    def create(provider: str, *, base_url: Optional[str] = None) -> BaseLLMClient:
        pid = _normalize_provider_id(provider)
        if not pid or pid == "anthropic":
            return AnthropicLLMClient()
        if pid == "openai":
            bu = str(base_url).strip() if base_url else None
            key = _resolve_openai_api_key("openai", bu)
            return OpenAILLMClient(base_url=bu, api_key=key)
        if pid == "openai-compatible":
            if not base_url or not str(base_url).strip():
                raise ValueError(
                    "provider 'openai-compatible' requires a non-empty base_url "
                    "(e.g. https://api.deepseek.com or http://localhost:11434/v1)"
                )
            bu_s = str(base_url).strip()
            key = _resolve_openai_api_key("openai-compatible", bu_s)
            return OpenAILLMClient(base_url=bu_s, api_key=key)
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
