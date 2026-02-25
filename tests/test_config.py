"""Basic tests for the authe SDK."""

import os
import pytest


def test_config_requires_api_key():
    """Config should raise if no API key is provided."""
    # Clear env var if set
    os.environ.pop("AUTHE_API_KEY", None)

    from authe.config import AutheConfig

    with pytest.raises(ValueError, match="API key required"):
        AutheConfig()


def test_config_from_env():
    """Config should read from environment variables."""
    os.environ["AUTHE_API_KEY"] = "ak_test123"
    os.environ["AUTHE_AGENT_NAME"] = "test-agent"

    from authe.config import AutheConfig

    config = AutheConfig()
    assert config.api_key == "ak_test123"
    assert config.agent_name == "test-agent"
    assert config.base_url == "https://api.authe.me"

    # Cleanup
    del os.environ["AUTHE_API_KEY"]
    del os.environ["AUTHE_AGENT_NAME"]


def test_config_args_override_env():
    """Explicit args should override env vars."""
    os.environ["AUTHE_API_KEY"] = "ak_from_env"

    from authe.config import AutheConfig

    config = AutheConfig(api_key="ak_from_args", agent_name="explicit-agent")
    assert config.api_key == "ak_from_args"
    assert config.agent_name == "explicit-agent"

    del os.environ["AUTHE_API_KEY"]


def test_safe_serialize():
    """_safe_serialize should handle nested data safely."""
    from authe.instrumentor import _safe_serialize

    result = _safe_serialize({"key": "value", "nested": {"a": 1}})
    assert result["key"] == "value"
    assert result["nested"]["a"] == 1


def test_safe_serialize_truncates_strings():
    """Long strings should be truncated."""
    from authe.instrumentor import _safe_serialize

    long_string = "a" * 1000
    result = _safe_serialize({"text": long_string})
    assert len(result["text"]) < 600
