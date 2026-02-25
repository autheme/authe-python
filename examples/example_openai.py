"""
Example: Using authe.me with an OpenAI agent.

1. Get your API key at https://authe.me
2. Set it: export AUTHE_API_KEY=ak_xxxxx
3. Run this script: python example_openai.py
4. View your agent's actions at dashboard.authe.me
"""

import authe

# One line. That's it.
authe.init(
    agent_name="inbox-summarizer",
    capabilities=["read:email", "send:slack"],
)

# Your agent code runs normally
from openai import OpenAI

client = OpenAI()

response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Summarize the latest news about AI agents."},
    ],
)

print(response.choices[0].message.content)

# authe.me automatically captured:
#   → the LLM call (model, token count, duration)
#   → any tool calls the agent made
#   → scope violations if the agent tried something unauthorized
#
# View it all at dashboard.authe.me
