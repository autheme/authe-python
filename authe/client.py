"""HTTP client for communicating with the authe.me API."""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from authe.config import AutheConfig

logger = logging.getLogger("authe")


class AutheClient:
    """Client that manages agent registration, token refresh, and action batching."""

    def __init__(self, config: AutheConfig):
        self.config = config
        self._http = httpx.Client(
            base_url=config.base_url,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

        # Session
        self.config.session_id = f"ses_{uuid.uuid4().hex[:16]}"

        # Action buffer — batches actions before sending
        self._buffer: list[dict] = []
        self._buffer_lock = threading.Lock()
        self._flush_interval = 5.0  # seconds
        self._max_buffer_size = 100

        # Start background flush thread
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        # Flush on exit
        atexit.register(self.flush)

        # Token refresh
        self._token_lock = threading.Lock()
        self._token_expires_at: float = 0

        if config.debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

    def register_or_authenticate(self):
        """Register the agent or authenticate if it already exists."""
        try:
            # First, try to register a new agent
            resp = self._http.post(
                "/v1/agents",
                json={
                    "name": self.config.agent_name,
                    "description": f"Auto-registered by authe SDK v{self._get_version()}",
                    "framework": self._detect_framework(),
                    "capabilities": self.config.capabilities,
                },
                headers={"Authorization": f"Bearer {self.config.api_key}"},
            )

            if resp.status_code == 201:
                data = resp.json()
                self.config.agent_id = data["agent"]["id"]
                logger.info(f"authe.me: registered agent '{self.config.agent_name}' ({self.config.agent_id})")
                self._refresh_token()
                return

            if resp.status_code == 409:
                # Agent already exists — fetch it and get a token
                logger.debug("authe.me: agent already registered, fetching token")
                self._fetch_existing_agent()
                return

            logger.warning(f"authe.me: registration returned {resp.status_code}: {resp.text}")

        except Exception as e:
            logger.warning(f"authe.me: failed to register agent: {e}")
            logger.warning("authe.me: running in offline mode — actions will be buffered locally")

    def _fetch_existing_agent(self):
        """Fetch existing agents and find ours by name."""
        try:
            resp = self._http.get(
                "/v1/agents",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
            )
            if resp.status_code == 200:
                agents = resp.json().get("agents", [])
                for agent in agents:
                    if agent["name"] == self.config.agent_name:
                        self.config.agent_id = agent["id"]
                        logger.info(f"authe.me: connected to agent '{self.config.agent_name}' ({self.config.agent_id})")
                        self._refresh_token()
                        return
            logger.warning("authe.me: could not find existing agent")
        except Exception as e:
            logger.warning(f"authe.me: failed to fetch agents: {e}")

    def _refresh_token(self):
        """Get a short-lived JWT token for the agent."""
        if not self.config.agent_id:
            return

        with self._token_lock:
            try:
                resp = self._http.get(
                    f"/v1/agents/{self.config.agent_id}/token",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.config.agent_token = data["token"]
                    self._token_expires_at = time.time() + data.get("expires_in", 900) - 60  # refresh 60s early
                    logger.debug("authe.me: agent token refreshed")
            except Exception as e:
                logger.warning(f"authe.me: failed to refresh token: {e}")

    def _ensure_token(self):
        """Ensure we have a valid agent token."""
        if time.time() >= self._token_expires_at:
            self._refresh_token()

    # ─── Action Tracking ───

    def track_action(
        self,
        tool: str,
        action_type: str = "tool_call",
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        status: str = "success",
        duration_ms: int = 0,
        signature: str = "",
    ):
        """
        Record an agent action.

        This is called automatically by instrumentors, but can also be called manually:

            from authe import get_client
            client = get_client()
            client.track_action("send_email", input_data={"to": "bob@example.com"})
        """
        action = {
            "session_id": self.config.session_id,
            "type": action_type,
            "tool": tool,
            "input": self._maybe_redact(input_data or {}),
            "output": self._maybe_redact(output_data or {}),
            "status": status,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signature": signature,
        }

        with self._buffer_lock:
            self._buffer.append(action)
            if len(self._buffer) >= self._max_buffer_size:
                self._send_batch()

    def flush(self):
        """Flush buffered actions to the API."""
        with self._buffer_lock:
            self._send_batch()

    def _send_batch(self):
        """Send buffered actions to the API. Must be called with _buffer_lock held."""
        if not self._buffer or not self.config.agent_id:
            return

        batch = self._buffer.copy()
        self._buffer.clear()

        self._ensure_token()

        if not self.config.agent_token:
            logger.warning(f"authe.me: no token, dropping {len(batch)} actions")
            return

        try:
            resp = self._http.post(
                "/v1/ingest",
                json={
                    "agent_id": self.config.agent_id,
                    "actions": batch,
                },
                headers={"Authorization": f"Bearer {self.config.agent_token}"},
            )

            if resp.status_code == 200:
                data = resp.json()
                logger.debug(
                    f"authe.me: sent {data.get('inserted', 0)} actions "
                    f"({data.get('alerts', 0)} alerts)"
                )
            else:
                logger.warning(f"authe.me: ingest returned {resp.status_code}: {resp.text}")
                # Put actions back in buffer for retry
                self._buffer = batch + self._buffer

        except Exception as e:
            logger.warning(f"authe.me: failed to send batch: {e}")
            # Put actions back in buffer for retry
            self._buffer = batch + self._buffer

    def _flush_loop(self):
        """Background thread that flushes the buffer periodically."""
        while self._running:
            time.sleep(self._flush_interval)
            try:
                self.flush()
            except Exception:
                pass

    # ─── Helpers ───

    def _maybe_redact(self, data: dict) -> dict:
        """Optionally redact sensitive-looking fields."""
        if not self.config.redact_pii:
            return data

        redacted = {}
        sensitive_keys = {"password", "token", "secret", "key", "authorization", "cookie", "ssn", "credit_card"}

        for k, v in data.items():
            if any(s in k.lower() for s in sensitive_keys):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, dict):
                redacted[k] = self._maybe_redact(v)
            else:
                redacted[k] = v

        return redacted

    def _detect_framework(self) -> str:
        """Detect which agent framework is being used."""
        try:
            import openai  # noqa
            return "openai"
        except ImportError:
            pass

        try:
            import langchain  # noqa
            return "langchain"
        except ImportError:
            pass

        try:
            import crewai  # noqa
            return "crewai"
        except ImportError:
            pass

        return "custom"

    def _get_version(self) -> str:
        try:
            from authe import __version__
            return __version__
        except Exception:
            return "0.1.0"

    def close(self):
        """Shutdown the client."""
        self._running = False
        self.flush()
        self._http.close()
