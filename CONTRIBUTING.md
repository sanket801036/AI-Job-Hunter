# Contributing

Thanks for taking a look. Bug reports, ideas and pull requests are all welcome.

## Set up

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on Linux / macOS)
pip install -r requirements.txt
copy .env.example .env            # keys are only needed for real scans, not for tests
python -m pytest -q
```

The tests use a throwaway SQLite file and mock every network call, so they run without
any API keys.

## Making a change

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep each pull request to one change, with a test for it.
3. Run `python -m pytest -q` before you push; CI runs the same command.
4. Never commit `.env`, tokens or real personal data. `profile.yaml` should stay generic.

## Ground rules for the LinkedIn part

- Only the public, logged-out job pages are used. Please don't add login, cookies or browser automation.
- Keep request rates low (a few pages per scan, with pauses). The project is meant for one person's job search.

## Where things live

| Folder | What it does |
|---|---|
| `app/linkedin/` | Search and job detail fetchers |
| `app/llm/` | LLM client with provider fallback |
| `app/judge.py` | Rules + LLM eligibility verdict |
| `app/notify/` | Telegram messages |
| `app/pipeline.py` | One full scan |
| `app/web/` | FastAPI dashboard and Telegram webhook |
| `tests/` | pytest suite |
