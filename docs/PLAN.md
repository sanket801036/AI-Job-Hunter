# AI Job Hunter: Plan

Finds new AI jobs on LinkedIn every few minutes, checks with an LLM whether I am eligible,
sends the good ones to Telegram, and tracks everything after that (application, referrals,
interview stages) on one dashboard.

## 1. Architecture

```
 GitHub Actions (cron, every 10 min)               Render (free web service)
 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”              â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
 â”‚ fetcher  -> LinkedIn guest API   â”‚              â”‚ FastAPI dashboard             â”‚
 â”‚ parser   -> JD, apply type, link â”‚   Neon       â”‚  - Jobs feed + full JD        â”‚
 â”‚ filter   -> AI-related?          â”‚â”€â”€Postgresâ”€â”€â”€â–¶â”‚  - Applications tracker       â”‚
 â”‚ judge    -> LLM eligibility JSON â”‚   (free)     â”‚  - Referrals / contacts       â”‚
 â”‚             (provider fallback)  â”‚â—€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”‚  - Interview pipeline         â”‚
 â”‚ notifier -> Telegram message     â”‚              â”‚  - Settings + health          â”‚
 â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜              â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                     â”‚                                          â–²
                     â–¼                                          â”‚
              Telegram bot  â”€â”€ buttons: Applied / Skip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ (webhook)
```

Why this split:
- Render free tier sleeps after 15 minutes idle, so a scheduler inside it would stop.
  GitHub Actions cron runs on its own (free for public repos). Note: GitHub may delay
  scheduled runs by a few minutes at busy times.
- The dashboard can sleep; it only needs to be up when I open it.
- Neon Postgres (free) is shared by both. SQLite for local development.

## 2. LinkedIn: no login, no clicking

- Use LinkedIn's public guest endpoints (the same ones the logged-out jobs page uses):
  - search: `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&geoId=102713980&f_TPR=r21600&f_WT=1,2,3&start=0`
  - job detail: `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<jobId>`
- The detail page gives the full JD (no "See more" click needed), company, location,
  posted time, applicant count, and the apply button: Easy Apply or an external company link.
- Do NOT log in with my LinkedIn account from a bot. Logged-in automation from a
  datacenter IP (GitHub/Render) gets flagged quickly and can restrict or ban the account.
- Polite rate: every 10 minutes, a few pages per run, random delay between requests,
  stop and back off on HTTP 429.

## 3. Eligibility check (LLM, JSON output)

Input: JD text + my profile (`profile.yaml`: 3+ years, skills, preferred locations, minimum CTC).
Output (Pydantic-validated JSON):

```json
{
  "is_ai_role": true,
  "min_years": 3, "max_years": 5,
  "seniority": "mid",               // junior | mid | senior | lead | principal
  "eligible": true,
  "match_score": 82,                // 0-100
  "matched_skills": ["LangGraph", "RAG", "FastAPI"],
  "missing_skills": ["Kubernetes"],
  "red_flags": ["contract role"],
  "reason": "3-5 years, Python + RAG + agents, Pune hybrid"
}
```

Rules on top of the LLM (deterministic, so the LLM cannot override them):
- min_years > 5, or title has Staff / Principal / Lead / Director -> not eligible
  (unless the JD says 3-6 years).
- Company on my skip list (aggregators like Joblet-AI, JobSphere, Spore N Sprouts) -> skip.
- Already seen job ID -> skip (dedupe).

Provider fallback: `AI_PROVIDERS=gemini,gemini2,mistral,cerebras,groq`. On error, timeout,
429 or invalid JSON, try the next one. Log which provider answered.

## 4. Telegram notification

```
ðŸŸ¢ AI Engineer - Krista (Pune, On-site)
Match 82% | 3-5 yrs | 1 applicant | 7 min ago
âœ… LangGraph, RAG, MCP, FastAPI   âŒ Kubernetes
Apply: Easy Apply   (or: Company site -> <link>)
LinkedIn: <job link>
Dashboard: <job page link>
[ Applied ] [ Skip ] [ Save ]
```

Buttons update the job status in the dashboard through a webhook.
Daily 9 PM digest: jobs found today, applied, follow-ups due.

## 5. Dashboard modules

1. **Jobs feed**: new jobs with match score, filters (eligible only, Easy Apply only, location,
   work type), full JD, LinkedIn link, apply link, Applied / Skip.
2. **Applications**: every applied job: date, resume file used, platform, CTC told, status.
3. **Referrals / people**: per company: person name, LinkedIn URL, role, connection sent date,
   accepted?, referral asked?, message used, which resume and JD it was for, outcome.
4. **Interview pipeline** (Kanban): Applied -> HR screen -> Assessment -> Tech 1 -> Tech 2 ->
   Manager/HR -> Offer / Rejected / Ghosted, with dates and notes per round.
5. **Follow-ups**: reminders: referral not answered in 3 days, no update in 7 days,
   interview tomorrow. Sent in the Telegram digest.
6. **Settings & connections**: one page for Telegram (bot token status, chat id, test button),
   search config (keywords, hours window, work type, interval), profile, LLM providers with a
   "test" button. Keys are never shown, only "connected / failing".
8. **Stats**: jobs found per day, eligible %, applied, referral reply rate, interview rate.

Login: one admin password (env var), because the dashboard URL is public.

## 6. Tech stack

Python 3.11, FastAPI, Jinja2 + HTMX + Tailwind (no React build step), SQLAlchemy 2 + Alembic,
httpx, selectolax for HTML parsing, Pydantic, python-telegram-bot (webhook mode), pytest.

## 7. Secrets

- `.env` locally, listed in `.gitignore`. A `.env.example` with empty values is committed.
- GitHub Actions: repository Secrets. Render: environment variables.
- Needed: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`,
  `GEMINI_API_KEY_2`, `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`, `GROQ_API_KEY` (optional),
  `DASHBOARD_PASSWORD`, `WEBHOOK_SECRET`.

## 8. Build order (small commits, one feature each)

| # | Step | Commit message |
|---|------|----------------|
| 1 | Repo skeleton, README, .gitignore, .env.example, config loader | `Set up project structure and config` |
| 2 | DB models + SQLite/Postgres session + Alembic | `Add database models for jobs and applications` |
| 3 | LinkedIn guest search fetcher + dedupe | `Fetch new jobs from LinkedIn search` |
| 4 | Job detail parser (JD, apply type, link, applicants) | `Parse job details and apply link` |
| 5 | LLM client with provider fallback | `Add LLM client with provider fallback` |
| 6 | Eligibility judge + rules + tests | `Check eligibility with LLM and rules` |
| 7 | Telegram notifier | `Send matching jobs to Telegram` |
| 8 | `run_once` pipeline + GitHub Actions cron | `Run the job pipeline on a schedule` |
| 9 | Dashboard: login + jobs feed + JD view | `Add dashboard with jobs feed` |
| 10 | Telegram buttons webhook | `Update job status from Telegram buttons` |
| 11 | Applications + resume tracking | `Track applications and resumes` |
| 12 | Referrals / people module | `Track referral contacts per company` |
| 13 | Interview pipeline Kanban | `Add interview pipeline board` |
| 14 | Follow-ups + daily digest | `Add follow-up reminders and daily digest` |
| 15 | Settings + connection tests | `Add settings page with connection checks` |
| 16 | Stats page | `Add application stats` |
| 17 | Deploy to Render + Neon, docs | `Deploy dashboard to Render` |
