# AI Job Hunter

Checks LinkedIn for new AI jobs every few minutes, reads the full job description,
asks an LLM whether I am a fit, and sends the good ones to Telegram. A small dashboard
then tracks what happens next: application, resume used, referral contacts and
interview rounds.

## How it works

```
GitHub Actions (every 10 min) -> LinkedIn guest search -> job details
  -> AI role? eligible? (LLM, with provider fallback) -> Telegram
                         |
                    Postgres (Neon)
                         |
              Dashboard (FastAPI on Render)
```

- No LinkedIn login. Only the public, logged-out job endpoints are used.
- LLM calls fall back to the next provider if one fails or is rate limited.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then fill in your keys
```

Scan once: `python -m app.pipeline`
Dashboard: `python -m uvicorn app.web.main:app --reload --port 8011`

## Deploy the dashboard on Render

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.web.main:app --host 0.0.0.0 --port $PORT`
- Environment: the same values as `.env` (plus `PYTHON_VERSION=3.11.9`).
- Then point the Telegram bot at it: `python scripts/set_webhook.py https://<your-app>.onrender.com`

After that, send **run now** or **status** to the bot.

The full plan and build order is in [docs/PLAN.md](docs/PLAN.md).
