"""Tests for LLM provider factory, VisionBridge, and Brain client resolution."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from llm_provider import (
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


def test_brain_client_for_role_passes_base_url():
    with patch("llm_provider.OpenAILLMClient") as mock_cls:
        brain_client_for_role(
            {
                "evaluator": "x",
                "evaluator_provider": "openai-compatible",
                "evaluator_base_url": "https://api.deepseek.com",
            },
            "evaluator",
        )
    mock_cls.assert_called_once_with(base_url="https://api.deepseek.com")


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
