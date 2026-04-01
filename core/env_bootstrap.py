"""Load API keys and other secrets from a repo-root ``.env`` before Brain / SDK use."""

from __future__ import annotations

from pathlib import Path


def load_harness_env() -> None:
    """Populate ``os.environ`` from ``.env`` at the repository root (if present).

    Uses ``python-dotenv`` when installed. Existing environment variables are not
    overwritten (``override=False``) so CI and shells keep precedence.

    Expected keys for Brain LLM clients (see SDK docs): ``ANTHROPIC_API_KEY``,
    ``OPENAI_API_KEY`` (also used by OpenAI-compatible servers such as DeepSeek
    when using the OpenAI SDK).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return

    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=repo_root / ".env", override=False)
