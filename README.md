# AI Job Hunter

[![Tests](https://github.com/sanket801036/AI-Job-Hunter/actions/workflows/tests.yml/badge.svg)](https://github.com/sanket801036/AI-Job-Hunter/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)

A personal job-search agent. It checks LinkedIn for new jobs every few minutes, reads
each full job description, asks an LLM whether your profile is a real fit, and sends the
good ones to Telegram within minutes of posting. A small dashboard then tracks what
happens next: the application, the resume you sent, referral contacts and interview rounds.

Built because the best roles get hundreds of applicants in the first hour.

## Features

- **Fresh jobs, fast**: scans every 5 to 10 minutes and only looks at jobs posted in the last few hours.
- **No LinkedIn login**: only the public, logged-out job pages are read, so your account is never at risk.
- **LLM fit check**: rules first (years asked, senior titles, blocked companies, duplicates), then an
  LLM returns a validated verdict with a match score, matched skills and missing skills.
- **Provider fallback**: Gemini, Groq, Mistral and Cerebras are tried in order, so one rate limit
  never stops a scan. All of them have free tiers.
- **Useful Telegram alerts**: match score, applicant count, how long ago it was posted, a warning
  for likely reposts, and Applied / Skip / Save buttons. Send `run now` or `status` to the bot any time.
- **Application tracker**: jobs feed, search profiles per keyword, resumes, applications with the
  exact resume sent, referral contacts per company, interview rounds and a scan history.
- **Runs free**: GitHub Actions for scans, Render free tier for the dashboard, Neon free Postgres.

## How it works

```
cron-job.org (every 5 min) ──> Render: /cron/scan ──> GitHub Actions: workflow_dispatch
Telegram "run now" ────────────────┘                        │
                                                            ▼
            LinkedIn guest search ──> job details ──> rules ──> LLM verdict ──> Telegram
                                                            │
                                                     Postgres (Neon)
                                                            │
                                             Dashboard (FastAPI on Render)
```

Scans run on GitHub's runners and the dashboard only starts them, so the free Render
instance stays light. A lease lock in Postgres makes sure two scans never run at once.
The GitHub schedule (every 10 minutes) is kept as a backup trigger.

## Use it for yourself

1. **Fork** this repo and edit `profile.yaml`: experience, skills, titles, locations and
   companies to skip. Keep it honest; the LLM compares every job against it.
2. **Database**: create a free Postgres on [Neon](https://neon.tech) and copy the connection string.
3. **Telegram**: create a bot with [@BotFather](https://t.me/BotFather) for the token, and get your
   chat id from [@userinfobot](https://t.me/userinfobot).
4. **LLM keys**: at least one of Gemini, Groq, Mistral or Cerebras (all have free tiers).
5. **GitHub secrets**: in your fork, *Settings → Secrets and variables → Actions*, add
   `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and your LLM keys. Scans now run
   on the GitHub schedule.
6. **Dashboard (optional)**:

   [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sanket801036/AI-Job-Hunter)

   Fill in the values Render asks for (set `GITHUB_REPO` to your fork), then point the bot at it:
   `python scripts/set_webhook.py https://<your-app>.onrender.com`
7. **Faster scans (optional)**: on [cron-job.org](https://cron-job.org), call
   `https://<your-app>.onrender.com/cron/scan?key=<WEBHOOK_SECRET>` every 5 minutes.

The dashboard's Settings page has the same guide in Hinglish.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on Linux / macOS)
pip install -r requirements.txt
copy .env.example .env            # then fill in your keys
python -m app.pipeline            # one scan
python -m uvicorn app.web.main:app --reload --port 8011   # dashboard
python -m pytest -q               # tests, no keys needed
```

All settings are in [.env.example](.env.example): search keywords, location, time window,
work types (on-site, remote, hybrid) and the LLM provider order.

## Project layout

| Path | What it does |
|---|---|
| `app/linkedin/` | Guest search and job detail fetchers, with retries on rate limits |
| `app/llm/` | One client for every provider, with fallback |
| `app/judge.py` | Rules + LLM eligibility verdict (Pydantic) |
| `app/notify/` | Telegram message formatting and sending |
| `app/pipeline.py` | One full scan, with the lock and scan history |
| `app/web/` | FastAPI dashboard, Telegram webhook and `/cron/scan` |
| `tests/` | pytest suite, network calls mocked |

## Responsible use

This is a personal tool for one person's job search. It reads only public job pages,
makes a few requests per scan with pauses between them, and never logs in. Please keep
it that way: don't raise the request rate or add login or browser automation. LinkedIn's
terms apply to you when you run it.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Sanket Kolhe
