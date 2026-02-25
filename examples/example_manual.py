"""
Example: Manual action tracking with the @track decorator.

Use this when you have custom tools that aren't auto-detected.
"""

import authe
from authe.instrumentor import track

authe.init(
    agent_name="custom-agent",
    capabilities=["read:email", "send:email", "read:calendar"],
)


@track("read_inbox")
def read_inbox(account: str, limit: int = 10):
    """Custom tool: read emails from inbox."""
    # Your actual email reading logic here
    return [
        {"from": "alice@example.com", "subject": "Meeting tomorrow"},
        {"from": "bob@example.com", "subject": "Project update"},
    ]


@track("send_email")
def send_email(to: str, subject: str, body: str):
    """Custom tool: send an email."""
    # Your actual email sending logic here
    print(f"Sending email to {to}: {subject}")
    return {"status": "sent", "message_id": "msg_123"}


# Use your tools normally — authe tracks everything
emails = read_inbox("me@company.com", limit=5)
send_email("alice@example.com", "Re: Meeting tomorrow", "Sounds good, see you there!")

# Flush to ensure all actions are sent
client = authe.get_client()
client.flush()

print("Done! Check dashboard.authe.me for the action timeline.")
