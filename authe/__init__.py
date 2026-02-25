"""
authe — The trust layer for AI agents.

Usage:
    import authe
    authe.init()

That's it. Your agent is now observable.
"""

from authe.client import AutheClient
from authe.config import AutheConfig
from authe.instrumentor import Instrumentor

__version__ = "0.2.0"
__all__ = ["init", "get_client"]

# Global client instance
_client: AutheClient | None = None
_instrumentor: Instrumentor | None = None


def init(
    api_key: str | None = None,
    agent_name: str | None = None,
    capabilities: list[str] | None = None,
    base_url: str = "https://api.authe.me",
    auto_instrument: bool = True,
    redact_pii: bool = False,
    debug: bool = False,
) -> AutheClient:
    """
    Initialize authe.me agent observability.

    Args:
        api_key: Your authe.me API key. Falls back to AUTHE_API_KEY env var.
        agent_name: Name for this agent. Falls back to AUTHE_AGENT_NAME or auto-detected.
        capabilities: Declared capabilities (e.g. ["read:email", "write:file"]).
        base_url: API endpoint. Default: https://api.authe.me
        auto_instrument: Auto-instrument detected frameworks. Default: True.
        redact_pii: Redact potentially sensitive data from logs. Default: False.
        debug: Enable debug logging. Default: False.

    Returns:
        AutheClient instance.

    Example:
        import authe
        authe.init()
    """
    global _client, _instrumentor

    config = AutheConfig(
        api_key=api_key,
        agent_name=agent_name,
        capabilities=capabilities or [],
        base_url=base_url,
        auto_instrument=auto_instrument,
        redact_pii=redact_pii,
        debug=debug,
    )

    _client = AutheClient(config)
    _client.register_or_authenticate()

    if auto_instrument:
        _instrumentor = Instrumentor(_client)
        _instrumentor.auto_instrument()

    return _client


def get_client() -> AutheClient | None:
    """Get the global AutheClient instance."""
    return _client
