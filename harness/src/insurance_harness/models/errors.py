"""Typed failures with metadata-only diagnostics."""


class ModelCallError(RuntimeError):
    """Never attach a request, response or underlying transport exception."""

    def __init__(
        self, outcome: str, *, stage: str = "", model: str = "", status_code: int | None = None,
    ) -> None:
        super().__init__(
            f"stage={stage} model={model} status_code={status_code} outcome={outcome}"
        )


class ModelConfigError(ModelCallError):
    """Invalid configuration or missing credentials; no send occurred."""


class TruncatedCompletion(ModelCallError):
    """Output is incomplete; retrying with the same budget cannot repair it."""


class InputTooLarge(ModelCallError):
    """Input exceeds the configured character budget."""


class ModelHTTPError(ModelCallError):
    """A non-retryable status or malformed response."""


class ModelUnavailable(ModelCallError):
    """Retryable failures exhausted the attempt allowance."""


class ModelBudgetExceeded(ModelCallError):
    """The shared ledger refused a send before it reached the transport."""
