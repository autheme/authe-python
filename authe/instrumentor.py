"""
Auto-instrumentation for AI agent frameworks.

Hooks into tool calls, API requests, and file operations
to capture actions without any code changes.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from authe.client import AutheClient

logger = logging.getLogger("authe")


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

        if self._patched:
            logger.info(f"authe.me: instrumented {', '.join(self._patched)}")
        else:
            logger.debug("authe.me: no frameworks detected, use client.track_action() manually")

    # ─── OpenAI ───

    def _instrument_openai(self):
        """Patch OpenAI client to capture completions and tool calls."""
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

                    # Extract tool calls from response
                    tool_calls = []
                    output = {}

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
                                output["content"] = msg.content[:500]  # truncate

                    if tool_calls:
                        output["tool_calls"] = tool_calls

                    # Track the LLM call
                    self.client.track_action(
                        tool="openai.chat.completions.create",
                        action_type="llm_call",
                        input_data={
                            "model": kwargs.get("model", "unknown"),
                            "messages_count": len(kwargs.get("messages", [])),
                            "tools_count": len(kwargs.get("tools", [])),
                            "has_tools": bool(kwargs.get("tools")),
                        },
                        output_data=output if not error_msg else {"error": error_msg},
                        status=status,
                        duration_ms=duration_ms,
                    )

                    # Track individual tool calls
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

    # ─── Subprocess (system commands) ───

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

            # Only track write operations — reads are too noisy
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
