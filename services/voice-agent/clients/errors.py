"""Custom exceptions for remote laptop services."""


class ServiceUnavailableError(Exception):
    """Raised when an STT/TTS/LLM (or backend) HTTP call fails after retries."""

    def __init__(self, service: str, message: str, *, url: str | None = None) -> None:
        self.service = service
        self.url = url
        super().__init__(f"{service} unavailable: {message}")


class ProviderConfigError(Exception):
    """Raised at session start when a provider is selected without a usable API key."""

    def __init__(self, service: str, provider: str, message: str) -> None:
        self.service = service
        self.provider = provider
        super().__init__(message)
