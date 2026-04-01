"""Tests for LLM provider factory, VisionBridge, and Brain client resolution."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from llm_provider import (
    LLMProviderFactory,
    VisionBridge,
    brain_client_for_role,
    extract_anthropic_message_text,
    extract_openai_completion_text,
)


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


def test_extract_openai_completion_text_string_content():
    msg = MagicMock()
    msg.content = "hi"
    ch = MagicMock()
    ch.message = msg
    resp = MagicMock()
    resp.choices = [ch]
    assert extract_openai_completion_text(resp) == "hi"
