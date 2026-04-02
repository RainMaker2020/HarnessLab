"""Load API keys and other secrets from a repo-root ``.env`` before Brain / SDK use."""

from __future__ import annotations

from pathlib import Path


def load_harness_env() -> None:
    """Populate ``os.environ`` from ``.env`` at the repository root (if present).

    Uses ``python-dotenv`` when installed. Existing environment variables are not
    overwritten (``override=False``) so CI and shells keep precedence.

    Expected keys for Brain LLM clients (see SDK docs): ``ANTHROPIC_API_KEY``;
    ``OPENAI_API_KEY`` for provider ``openai``; ``DEEPSEEK_API_KEY`` or
    ``OPENAI_API_KEY`` for DeepSeek (``openai-compatible`` + ``api.deepseek.com``);
    ``OPENAI_COMPATIBLE_API_KEY`` or ``OPENAI_API_KEY`` for other compatible
    servers. Per-role model ids are configured in ``harness.yaml`` (``models``);
    optional env overrides ``HARNESS_MODEL_*`` are documented on
    ``HarnessConfig.effective_models``.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return

    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=repo_root / ".env", override=False)
