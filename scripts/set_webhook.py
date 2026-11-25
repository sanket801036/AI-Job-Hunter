"""Point the Telegram bot at the deployed dashboard.

Usage: python scripts/set_webhook.py https://your-app.onrender.com
Reads TELEGRAM_BOT_TOKEN and WEBHOOK_SECRET from .env.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/set_webhook.py https://your-app.onrender.com")
    base = sys.argv[1].rstrip("/")
    s = get_settings()
    if not (s.telegram_bot_token and s.webhook_secret):
        sys.exit("TELEGRAM_BOT_TOKEN and WEBHOOK_SECRET must be set in .env")
    api = f"https://api.telegram.org/bot{s.telegram_bot_token}"
    r = httpx.post(f"{api}/setWebhook", json={
        "url": f"{base}/telegram/webhook",
        "secret_token": s.webhook_secret,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }, timeout=20)
    print(r.json().get("description", r.text))
    httpx.post(f"{api}/setMyCommands", json={"commands": [
        {"command": "run", "description": "Search LinkedIn now"},
        {"command": "status", "description": "Jobs found in the last 24 hours"},
    ]}, timeout=20)


if __name__ == "__main__":
    main()
