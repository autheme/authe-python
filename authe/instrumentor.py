"""
Auto-instrumentation for AI agent frameworks.

Hooks into tool calls, API requests, HTTP, and file operations
to capture actions without any code changes.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from authe.client import AutheClient

logger = logging.getLogger("authe")

# ─── Cost Estimation ───

TOKEN_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-4-sonnet": {"input": 3.00, "output": 15.00},
    "claude-4-opus": {"input": 15.00, "output": 75.00},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost in USD for a model call. Returns None if model unknown."""
    for key, pricing in TOKEN_PRICING.items():
        if key in model.lower():
            cost = (input_tokens / 1_000_000 * pricing["input"]) + \
                   (output_tokens / 1_000_000 * pricing["output"])
            return round(cost, 6)
    return None


class Instrumentor:
    """Automatically instruments detected agent frameworks."""

    def __init__(self, client: AutheClient):
        self.client = client
        self._patched: list[str] = []

    def auto_instrument(self):
        """Detect and instrument all available frameworks."""
        self._instrument_openai()
        self._instrument_langchain()
        self._instrument_subprocess()
        self._instrument_file_ops()
        self._instrument_http()

        if self._patched:
            logger.info(f"authe.me: instrumented {', '.join(self._patched)}")
        else:
            logger.debug("authe.me: no frameworks detected, use client.track_action() manually")

    # ─── OpenAI ───

    def _instrument_openai(self):
        """Patch OpenAI client to capture completions, tool calls, and cost."""
        try:
            import openai
        except ImportError:
            return

        try:
            from openai.resources.chat import completions as chat_mod

            original_create = chat_mod.Completions.create

            @functools.wraps(original_create)
            def patched_create(self_inner, *args, **kwargs):
                start = time.time()
                status = "success"
                result = None
                error_msg = None

                try:
                    result = original_create(self_inner, *args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = int((time.time() - start) * 1000)

                    tool_calls = []
                    output = {}
                    model = kwargs.get("model", "unknown")
                    input_tokens = 0
                    output_tokens = 0

                    if result and hasattr(result, "choices"):
                        for choice in result.choices:
                            msg = choice.message
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tool_calls.append({
                                        "id": tc.id,
                                        "function": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    })
                            if hasattr(msg, "content") and msg.content:
                                output["content"] = msg.content[:500]

                    if result and hasattr(result, "usage") and result.usage:
                        input_tokens = result.usage.prompt_tokens or 0
                        output_tokens = result.usage.completion_tokens or 0
                        model = getattr(result, "model", model) or model

                    if tool_calls:
                        output["tool_calls"] = tool_calls

                    cost = estimate_cost(model, input_tokens, output_tokens)

                    self.client.track_action(
                        tool="openai.chat.completions.create",
                        action_type="llm_call",
                        input_data={
                            "model": model,
                            "messages_count": len(kwargs.get("messages", [])),
                            "tools_count": len(kwargs.get("tools", [])),
                            "has_tools": bool(kwargs.get("tools")),
                            "input_tokens": input_tokens,
                        },
                        output_data={
                            **(output if not error_msg else {"error": error_msg}),
                            "output_tokens": output_tokens,
                            "cost_usd": cost,
                        },
                        status=status,
                        duration_ms=duration_ms,
                    )

                    for tc in tool_calls:
                        self.client.track_action(
                            tool=tc["function"],
                            action_type="tool_call",
                            input_data={"arguments": tc["arguments"]},
                            status="success",
                            duration_ms=0,
                        )

            chat_mod.Completions.create = patched_create
            self._patched.append("openai")

        except Exception as e:
            logger.debug(f"authe.me: failed to instrument openai: {e}")

    # ─── LangChain ───

    def _instrument_langchain(self):
        """Patch LangChain to capture tool invocations."""
        try:
            from langchain_core.tools import BaseTool
        except ImportError:
            try:
                from langchain.tools import BaseTool
            except ImportError:
                return

        try:
            original_run = BaseTool.run

            @functools.wraps(original_run)
            def patched_run(self_inner, *args, **kwargs):
                start = time.time()
                status = "success"
                result = None
                error_msg = None

                try:
                    result = original_run(self_inner, *args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = int((time.time() - start) * 1000)

                    self.client.track_action(
                        tool=getattr(self_inner, "name", "langchain_tool"),
                        action_type="tool_call",
                        input_data={"args": str(args)[:500], "kwargs": _safe_serialize(kwargs)},
                        output_data={"result": str(result)[:500]} if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

            BaseTool.run = patched_run
            self._patched.append("langchain")

        except Exception as e:
            logger.debug(f"authe.me: failed to instrument langchain: {e}")

    # ─── HTTP Requests ───

    def _instrument_http(self):
        """Patch httpx and urllib3/requests to capture outbound HTTP calls."""
        patched_any = False

        # --- httpx ---
        try:
            import httpx

            original_send = httpx.Client.send

            authe_base = self.client.config.base_url

            @functools.wraps(original_send)
            def patched_send(self_inner, request, *args, **kwargs):
                url = str(request.url)

                # Skip authe's own API calls
                if authe_base in url:
                    return original_send(self_inner, request, *args, **kwargs)

                start = time.time()
                status = "success"
                response = None
                error_msg = None

                try:
                    response = original_send(self_inner, request, *args, **kwargs)
                    if response.status_code >= 400:
                        status = "error"
                    return response
                except Exception as e:
                    status = "error"
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = int((time.time() - start) * 1000)

                    self.client.track_action(
                        tool="http.request",
                        action_type="http",
                        input_data={
                            "method": request.method,
                            "url": url[:500],
                            "headers": {k: v for k, v in list(request.headers.items())[:10]
                                        if k.lower() not in ("authorization", "cookie", "x-api-key")},
                        },
                        output_data={
                            "status_code": response.status_code if response else None,
                            "content_length": len(response.content) if response else None,
                        } if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

            httpx.Client.send = patched_send
            patched_any = True

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"authe.me: failed to instrument httpx: {e}")

        # --- requests/urllib3 ---
        try:
            import requests

            original_request = requests.Session.request

            authe_base = self.client.config.base_url

            @functools.wraps(original_request)
            def patched_request(self_inner, method, url, *args, **kwargs):
                if authe_base in str(url):
                    return original_request(self_inner, method, url, *args, **kwargs)

                start = time.time()
                status = "success"
                response = None
                error_msg = None

                try:
                    response = original_request(self_inner, method, url, *args, **kwargs)
                    if response.status_code >= 400:
                        status = "error"
                    return response
                except Exception as e:
                    status = "error"
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = int((time.time() - start) * 1000)

                    self.client.track_action(
                        tool="http.request",
                        action_type="http",
                        input_data={
                            "method": method,
                            "url": str(url)[:500],
                        },
                        output_data={
                            "status_code": response.status_code if response else None,
                            "content_length": len(response.content) if response else None,
                        } if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

            requests.Session.request = patched_request
            patched_any = True

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"authe.me: failed to instrument requests: {e}")

        if patched_any:
            self._patched.append("http")

    # ─── Subprocess ───

    def _instrument_subprocess(self):
        """Patch subprocess to capture system command execution."""
        try:
            import subprocess

            original_run = subprocess.run

            @functools.wraps(original_run)
            def patched_run(*args, **kwargs):
                start = time.time()
                status = "success"
                result = None
                error_msg = None

                try:
                    result = original_run(*args, **kwargs)
                    if result.returncode != 0:
                        status = "error"
                    return result
                except Exception as e:
                    status = "error"
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = int((time.time() - start) * 1000)

                    cmd = args[0] if args else kwargs.get("args", "unknown")
                    if isinstance(cmd, list):
                        cmd = " ".join(str(c) for c in cmd)

                    self.client.track_action(
                        tool="subprocess.run",
                        action_type="system_command",
                        input_data={"command": str(cmd)[:500]},
                        output_data={
                            "returncode": result.returncode if result else None,
                            "stdout": str(result.stdout)[:200] if result and result.stdout else None,
                        } if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

            subprocess.run = patched_run
            self._patched.append("subprocess")

        except Exception as e:
            logger.debug(f"authe.me: failed to instrument subprocess: {e}")

    # ─── File operations ───

    def _instrument_file_ops(self):
        """Patch builtins.open to capture file read/write operations."""
        import builtins

        original_open = builtins.open
        client = self.client

        @functools.wraps(original_open)
        def patched_open(file, mode="r", *args, **kwargs):
            result = original_open(file, mode, *args, **kwargs)

            if any(m in str(mode) for m in ("w", "a", "x")):
                client.track_action(
                    tool="file.write",
                    action_type="file_operation",
                    input_data={"path": str(file), "mode": str(mode)},
                    status="success",
                    duration_ms=0,
                )

            return result

        builtins.open = patched_open
        self._patched.append("file_ops")


# ─── Decorator for manual instrumentation ───

def track(tool_name: str | None = None):
    """
    Decorator to manually track a function as an agent action.

    Usage:
        from authe.instrumentor import track

        @track("send_email")
        def send_email(to, subject, body):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from authe import get_client
            client = get_client()

            name = tool_name or func.__name__
            start = time.time()
            status = "success"
            result = None
            error_msg = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = int((time.time() - start) * 1000)
                if client:
                    client.track_action(
                        tool=name,
                        input_data=_safe_serialize(kwargs) if kwargs else {"args": str(args)[:500]},
                        output_data={"result": str(result)[:500]} if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

        return wrapper
    return decorator


def _safe_serialize(data: Any, max_depth: int = 3) -> dict:
    """Safely serialize data for logging, handling non-JSON types."""
    if max_depth <= 0:
        return {"_truncated": True}

    if isinstance(data, dict):
        return {str(k): _safe_serialize(v, max_depth - 1) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return {"_list": [_safe_serialize(v, max_depth - 1) for v in data[:20]]}
    elif isinstance(data, (str, int, float, bool, type(None))):
        if isinstance(data, str) and len(data) > 500:
            return data[:500] + "..."
        return data
    else:
        return str(data)[:500]
