"""Configuration for the authe SDK."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass, field


@dataclass
class AutheConfig:
    """SDK configuration, resolved from args + environment variables."""

    api_key: str | None = None
    agent_name: str | None = None
    capabilities: list[str] = field(default_factory=list)
    base_url: str = "https://api.authe.me"
    auto_instrument: bool = True
    redact_pii: bool = False
    debug: bool = False

    # Internal — set after resolution
    agent_id: str | None = None
    agent_token: str | None = None
    session_id: str | None = None

    def __post_init__(self):
        # Resolve from environment
        self.api_key = self.api_key or os.environ.get("AUTHE_API_KEY")
        self.agent_name = self.agent_name or os.environ.get("AUTHE_AGENT_NAME") or self._detect_agent_name()
        self.base_url = self.base_url.rstrip("/")

        if not self.api_key:
            raise ValueError(
                "authe.me API key required. Pass api_key= to authe.init() "
                "or set the AUTHE_API_KEY environment variable.\n"
                "Get your key at https://authe.me"
            )

    def _detect_agent_name(self) -> str:
        """Auto-generate an agent name from the environment."""
        # Try script filename
        script = os.path.basename(sys.argv[0]) if sys.argv[0] else "agent"
        script = script.replace(".py", "").replace("_", "-")
        hostname = socket.gethostname()[:12]
        return f"{script}-{hostname}"
