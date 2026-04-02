"""Tests for ModelRouter.resolve (model + Brain provider metadata)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.config.model_router import ModelRouter, ModelRoleResolution


def test_resolve_generator_has_no_brain_provider():
    cfg = type("C", (), {"models": {"generator": "claude-haiku-4-6"}})()
    r = ModelRouter(cfg).resolve("generator")
    assert r == ModelRoleResolution(model="claude-haiku-4-6", provider=None, base_url=None)


def test_resolve_evaluator_defaults_to_anthropic():
    cfg = type("C", (), {"models": {"evaluator": "claude-3-5-sonnet-20241022"}})()
    r = ModelRouter(cfg).resolve("evaluator")
    assert r.model == "claude-3-5-sonnet-20241022"
    assert r.provider == "anthropic"
    assert r.base_url is None


def test_resolve_evaluator_openai():
    cfg = type(
        "C",
        (),
        {"models": {"evaluator": "gpt-4o", "evaluator_provider": "openai"}},
    )()
    r = ModelRouter(cfg).resolve("evaluator")
    assert r.model == "gpt-4o"
    assert r.provider == "openai"


def test_resolve_contract_verifier_with_compatible_and_base_url():
    cfg = type(
        "C",
        (),
        {
            "models": {
                "contract_verifier": "deepseek-reasoner",
                "contract_verifier_provider": "openai-compatible",
                "contract_verifier_base_url": "https://api.deepseek.com",
            }
        },
    )()
    r = ModelRouter(cfg).resolve("contract_verifier")
    assert r.model == "deepseek-reasoner"
    assert r.provider == "openai-compatible"
    assert r.base_url == "https://api.deepseek.com"
