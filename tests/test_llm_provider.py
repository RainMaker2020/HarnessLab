"""Tests for LLM provider factory, VisionBridge, and Brain client resolution."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.llm.llm_provider import (
    LLMProviderFactory,
    VisionBridge,
    _chat_completions_create_with_token_budget,
    brain_client_for_role,
    extract_anthropic_message_text,
    extract_openai_completion_text,
)

try:
    from openai import BadRequestError
except ImportError:  # pragma: no cover
    BadRequestError = Exception  # type: ignore[misc, assignment]


def test_vision_bridge_anthropic_block_has_png_media_type():
    raw = b"\x89PNG\r\n\x1a\n"
    block = VisionBridge.png_bytes_to_anthropic_image_block(raw)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert block["source"]["type"] == "base64"


def test_vision_bridge_openai_data_url_prefix():
    raw = b"\xff\xd8\xff"
    url = VisionBridge.png_bytes_to_openai_data_url(raw)
    assert url.startswith("data:image/png;base64,")


def test_factory_rejects_openai_compatible_without_base_url():
    with pytest.raises(ValueError, match="base_url"):
        LLMProviderFactory.create("openai-compatible", base_url=None)


def test_brain_client_for_role_passes_base_url(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    with patch("harness.llm.llm_provider.OpenAILLMClient") as mock_cls:
        brain_client_for_role(
            {
                "evaluator": "x",
                "evaluator_provider": "openai-compatible",
                "evaluator_base_url": "https://api.deepseek.com",
            },
            "evaluator",
        )
    mock_cls.assert_called_once_with(
        base_url="https://api.deepseek.com",
        api_key=None,
    )


def test_factory_passes_deepseek_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    with patch("harness.llm.llm_provider.OpenAILLMClient") as mock_cls:
        LLMProviderFactory.create(
            "openai-compatible",
            base_url="https://api.deepseek.com",
        )
    mock_cls.assert_called_once_with(
        base_url="https://api.deepseek.com",
        api_key="sk-deepseek-test",
    )


def test_factory_openai_passes_openai_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    with patch("harness.llm.llm_provider.OpenAILLMClient") as mock_cls:
        LLMProviderFactory.create("openai", base_url=None)
    mock_cls.assert_called_once_with(base_url=None, api_key="sk-openai-test")


def test_factory_passes_openai_compatible_api_key_for_non_deepseek_host(monkeypatch):
    """Generic compatible servers use OPENAI_COMPATIBLE_API_KEY before OPENAI_API_KEY."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-groq-or-local")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fallback")
    with patch("harness.llm.llm_provider.OpenAILLMClient") as mock_cls:
        LLMProviderFactory.create("openai-compatible", base_url="https://api.groq.com/openai/v1")
    mock_cls.assert_called_once_with(
        base_url="https://api.groq.com/openai/v1",
        api_key="sk-groq-or-local",
    )


def test_anthropic_client_passes_explicit_api_key_when_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-explicit")
    with patch("harness.llm.llm_provider.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = MagicMock()
        from harness.llm.llm_provider import AnthropicLLMClient

        AnthropicLLMClient()
    mock_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-explicit")


def test_anthropic_client_omits_api_key_kwarg_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("harness.llm.llm_provider.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = MagicMock()
        from harness.llm.llm_provider import AnthropicLLMClient

        AnthropicLLMClient()
    mock_anthropic.Anthropic.assert_called_once_with()


def test_extract_anthropic_message_text_from_blocks():
    block = MagicMock()
    block.type = "text"
    block.text = "hello"
    msg = MagicMock()
    msg.content = [block]
    assert extract_anthropic_message_text(msg) == "hello"


def test_token_budget_succeeds_on_first_call_without_retry():
    mock_client = MagicMock()
    ok = MagicMock()
    mock_client.chat.completions.create.return_value = ok
    out = _chat_completions_create_with_token_budget(
        mock_client,
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
    )
    assert out is ok
    mock_client.chat.completions.create.assert_called_once()
    assert mock_client.chat.completions.create.call_args.kwargs["max_tokens"] == 256


def test_token_budget_retries_with_max_completion_tokens_after_bad_request():
    pytest.importorskip("openai", reason="openai package not installed")
    mock_client = MagicMock()
    ok = MagicMock()
    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.text = "max_tokens is not supported for this model"
    err = BadRequestError("unsupported max_tokens", response=resp_400, body=None)
    mock_client.chat.completions.create.side_effect = [err, ok]
    out = _chat_completions_create_with_token_budget(
        mock_client,
        model="o3-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
    )
    assert out is ok
    assert mock_client.chat.completions.create.call_count == 2
    second = mock_client.chat.completions.create.call_args_list[1].kwargs
    assert second["max_completion_tokens"] == 128
    assert "max_tokens" not in second


def test_token_budget_does_not_retry_on_401():
    pytest.importorskip("openai", reason="openai package not installed")
    mock_client = MagicMock()
    resp_401 = MagicMock()
    resp_401.status_code = 401
    err = BadRequestError("Unauthorized", response=resp_401, body=None)
    mock_client.chat.completions.create.side_effect = err
    with pytest.raises(BadRequestError):
        _chat_completions_create_with_token_budget(
            mock_client,
            model="m",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=10,
        )
    mock_client.chat.completions.create.assert_called_once()


def test_extract_openai_completion_text_string_content():
    msg = MagicMock()
    msg.content = "hi"
    ch = MagicMock()
    ch.message = msg
    resp = MagicMock()
    resp.choices = [ch]
    assert extract_openai_completion_text(resp) == "hi"
