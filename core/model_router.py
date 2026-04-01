"""ModelRouter — resolves the AI model for each pipeline role."""


class ModelRouter:
    """Responsibility: Resolves the correct model for each harness role.

    Reads the nested ``models`` map from HarnessConfig (sourced from harness.yaml)
    and returns the appropriate claude CLI arguments for a given role (planner,
    generator, evaluator). Falls back to DEFAULTS when a role is not specified in
    config. No model string is ever hardcoded in Worker or Orchestrator code.
    """

    DEFAULTS = {
        "planner": "claude-sonnet-4-6",
        "generator": "claude-sonnet-4-6",
        "evaluator": "claude-3-5-sonnet-20241022",
        "contract_verifier": "claude-3-5-sonnet-20241022",
    }

    def __init__(self, config) -> None:
        """Initialize with a HarnessConfig that exposes a ``models`` dict."""
        self.config = config

    def get_model(self, role: str) -> str:
        """Return the model identifier for the given role.

        Looks up ``config.models[role]`` first; falls back to DEFAULTS[role],
        then to the generic baseline if neither is defined.
        """
        models = getattr(self.config, "models", {}) or {}
        return models.get(role) or self.DEFAULTS.get(role, "claude-sonnet-4-6")

    def get_model_args(self, role: str = "generator") -> list:
        """Return CLI args to specify the model for the given role.

        Returns a list suitable for extending a subprocess command list.
        Example: ['--model', 'claude-3-5-haiku']
        """
        return ["--model", self.get_model(role)]
