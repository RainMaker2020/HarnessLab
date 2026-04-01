"""ModelRouter — resolves the AI model for each harness invocation."""


class ModelRouter:
    """Responsibility: Resolves the AI model to use for a given task invocation.

    Reads model configuration dynamically from HarnessConfig (sourced from harness.yaml)
    and returns the appropriate claude CLI arguments. No model string is ever hardcoded
    in the orchestrator. Designed to support per-task model overrides in the future
    without changing Worker or Orchestrator code.
    """

    def __init__(self, config) -> None:
        """Initialize with a HarnessConfig that exposes claude_model."""
        self.config = config

    def get_model_args(self) -> list:
        """Return CLI args to specify the model for the claude command.

        Returns a list suitable for extending a subprocess command list.
        Example: ['--model', 'claude-sonnet-4-6']
        """
        return ["--model", self.config.claude_model]

    def current_model(self) -> str:
        """Return the raw model identifier string from config."""
        return self.config.claude_model
