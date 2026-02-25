# authe

The trust layer for AI agents. Observability, identity, and reputation in one line of code.

[![PyPI](https://img.shields.io/pypi/v/authe)](https://pypi.org/project/authe/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Install

```bash
pip install authe
```

## Quick Start

```python
import authe
authe.init()

# That's it. Your agent is now observable.
# View actions at dashboard.authe.me
```

## What it does

`authe.init()` automatically instruments your agent and captures:

- **Every tool call** — function name, inputs, outputs, duration
- **LLM requests** — model, message count, tool usage
- **File operations** — writes tracked with path and mode
- **System commands** — subprocess calls captured
- **Scope violations** — alerts when agent exceeds declared capabilities

All actions are sent to your dashboard at [dashboard.authe.me](https://dashboard.authe.me) with a tamper-proof audit trail.

## Configuration

```python
import authe

authe.init(
    api_key="ak_xxxxx",          # or set AUTHE_API_KEY env var
    agent_name="my-agent",        # auto-detected if not set
    capabilities=["read:email", "write:file"],  # declared permissions
    redact_pii=True,              # redact sensitive fields
)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AUTHE_API_KEY` | Your API key (required) |
| `AUTHE_AGENT_NAME` | Agent name (optional, auto-detected) |

## Manual Tracking

For custom tools that aren't auto-detected:

```python
from authe.instrumentor import track

@track("send_email")
def send_email(to, subject, body):
    # your code here
    pass
```

Or track directly:

```python
from authe import get_client

client = get_client()
client.track_action(
    tool="custom_tool",
    input_data={"key": "value"},
    output_data={"result": "done"},
    status="success",
)
```

## Supported Frameworks

| Framework | Auto-instrumented |
|-----------|:-:|
| OpenAI | ✅ |
| LangChain | ✅ |
| CrewAI | 🔜 |
| AutoGPT | 🔜 |
| Custom agents | via `@track` decorator |

## How it works

1. `authe.init()` registers your agent and gets a short-lived token
2. Actions are captured via monkey-patching (zero code changes needed)
3. Actions are batched and sent to the API every 5 seconds
4. Your dashboard shows a real-time timeline of everything your agent did
5. Scope violations trigger alerts automatically

## Links

- **Website**: [authe.me](https://authe.me)
- **Dashboard**: [dashboard.authe.me](https://dashboard.authe.me)
- **API Docs**: [docs.authe.me](https://docs.authe.me)
- **GitHub**: [github.com/autheme](https://github.com/autheme)

## License

MIT
