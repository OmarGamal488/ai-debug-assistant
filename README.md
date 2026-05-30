# AI Debug Assistant

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=flat&logo=fastapi&logoColor=white)
![SQLModel](https://img.shields.io/badge/SQLModel-0.0.38-7E56C2?style=flat)
![uv](https://img.shields.io/badge/uv-managed-FDDF5B?style=flat&logo=astral&logoColor=black)
![Lightning AI](https://img.shields.io/badge/AI-Lightning%20AI-792EE5?style=flat)
![Tests](https://img.shields.io/badge/tests-11%20passing-22c55e?style=flat)
![SSR](https://img.shields.io/badge/rendering-server--side-1f6feb?style=flat)
![ITI](https://img.shields.io/badge/ITI-AI%20Intake%2046-FF6B35?style=flat)

A server-side-rendered FastAPI web app that turns a coding bug into a
categorised, difficulty-rated, AI-recommended fix — and files it in
a per-user **Debugbook**, a Jupyter-notebook-style log of every
analysis you have ever run.

Built as the capstone for the **FastAPI** course on the **AI track,
Intake 46** at the Information Technology Institute (ITI).

---

## At a glance

- **Stack** — FastAPI · Jinja2 (SSR) · SQLite · SQLModel · Lightning AI (OpenAI-compatible LLM endpoint)
- **Auth** — stateless signed cookies (`itsdangerous`) + bcrypt-hashed passwords (`passlib`)
- **AI integration** — fault-tolerant: every submission persists a row with `SUCCESS`, `FAILED`, or `PENDING` plus the AI's verdict or the captured error
- **Frontend** — "Debugbook" theme: Jupyter-notebook metaphor in monospace, mint-emerald accent on a dot-grid canvas, GSAP-animated, Prism.js code highlighting, marked.js + DOMPurify markdown for AI recommendations
- **Tests** — 11 pytest integration tests covering register / login / auth-redirect / submit / IDOR / logout, in-memory SQLite, ~4 seconds end-to-end

---

## Features

- User registration and login with bcrypt password hashing
- Stateless signed session cookies (`httponly`, `samesite=lax`); no session table on disk
- Submission form (programming language + free-text description)
- Per-user history rendered as Jupyter `In[n]:` / `Out[n]:` cell pairs, newest first
- Three-key AI analysis per submission — category, difficulty (Beginner / Intermediate / Advanced), recommendation
- Live full-text search, status filter pills, and sort toggle on the history
- Code syntax highlighting on submitted snippets (Prism.js, 13 languages)
- Safe Markdown rendering of AI recommendations (marked.js + DOMPurify)
- GSAP entrance and interaction animations, fully gated behind `prefers-reduced-motion`
- Server-side multi-tenant isolation: every read filters by `WHERE user_id = ?`, verified by a dedicated IDOR test

---

## Quick start

### Prerequisites

- Python 3.12 or newer (the project runs on 3.13)
- [uv](https://docs.astral.sh/uv/) for dependency management

### Setup

```bash
git clone https://github.com/OmarGamal488/ai-debug-assistant.git
cd ai-debug-assistant
uv sync
cp .env.example .env
# edit .env and set LIGHTNING_API_KEY and SECRET_KEY
```

### Run

```bash
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Then open <http://127.0.0.1:8000/login>, register an account, and
submit a coding problem.

### Run the tests

```bash
.venv/bin/python -m pytest -q
```

All 11 tests should pass in roughly 4 seconds.

---

## Configuration

Required environment variables (place them in `.env`, which is
gitignored):

| Variable | Description |
|---|---|
| `LIGHTNING_API_KEY` | Your Lightning AI API key — get one from <https://lightning.ai> |
| `LIGHTNING_BASE_URL` | OpenAI-compatible endpoint, e.g. `https://lightning.ai/api/v1/` |
| `LIGHTNING_MODEL` | Model identifier, e.g. `lightning-ai/deepseek-v4-pro` |
| `SECRET_KEY` | Random ≥ 32-character string used to sign session cookies |

Generate `SECRET_KEY` with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The application refuses to start if `SECRET_KEY` is missing or
shorter than 32 characters — turning a silent vulnerability into a
loud startup failure.

---

## Project structure

```
ai-debug-assistant/
├── app/                       # all Python source under one package
│   ├── main.py                # FastAPI routes
│   ├── database.py            # SQLAlchemy engine + per-request session
│   ├── models.py              # SQLModel tables (User, ReviewSession)
│   ├── security.py            # password hashing + signed cookies
│   └── ai_service.py          # Lightning AI call, isolated and fault-tolerant
├── templates/                 # Jinja2 SSR templates
│   ├── base.html              # shared shell — GSAP + Prism + marked
│   ├── login.html
│   ├── register.html
│   └── index.html             # the Debugbook dashboard
├── style/main.css             # served at /style/main.css via StaticFiles
├── tests/test_app.py          # 11 pytest integration tests
├── pyproject.toml
└── uv.lock                    # exact pinned versions
```

---

## Architecture

### Routing layer — `app/main.py`

Eight SSR routes. Form-driven, no JSON API. Every POST that mutates
state returns `303 See Other` so refreshing the resulting GET is
idempotent (the Post-Redirect-Get pattern). `get_current_user` is a
plain helper, not a FastAPI `Depends`, so protected routes can
redirect to `/login` instead of raising a 401.

### Persistence — `app/database.py` and `app/models.py`

SQLAlchemy engine + per-request SQLModel `Session` via the
`get_session()` dependency. Two tables, one 1-to-N relationship:

```
users (id PK, username UNIQUE, email UNIQUE, hashed_password)
review_sessions (id PK, user_id FK→users.id INDEX,
                 language, issue_description,
                 ai_category, ai_difficulty, ai_recommendation,
                 ai_status, error_message, created_at)
```

`Relationship(back_populates=...)` is declared on both sides so
`user.sessions` and `review.user` are convenient Python attributes
on top of the foreign key.

### Authentication — `app/security.py`

- **bcrypt via passlib's `CryptContext`.** Pinned to `bcrypt>=4.0.1,<4.1`
  because passlib 1.7.4 reads `bcrypt.__about__`, which was removed
  in bcrypt 4.1.
- **Stateless signed cookies via `itsdangerous.URLSafeTimedSerializer`.**
  The cookie payload is the `user_id`; the signature uses
  `SECRET_KEY`. No sessions table on disk — every request decodes
  and verifies the cookie directly.
- Cookies are `httponly` + `samesite=lax`. Set `secure=True` for
  HTTPS production deploys.

### AI service — `app/ai_service.py`

A single public function: `analyze_issue(language, issue_description)
-> dict`. The dict always has exactly five keys:
`ai_category`, `ai_difficulty`, `ai_recommendation`, `ai_status`,
`error_message`.

The entire body sits inside `try/except Exception`, so any failure —
network, bad API key, rate limit, invalid JSON, unexpected response
shape — returns a `FAILED` dict instead of raising. The `/submit`
route then persists the row with the failure visible to the user.

The call uses the official OpenAI SDK pointed at Lightning AI's
OpenAI-compatible endpoint, with `response_format={"type":
"json_object"}` (JSON mode) and `temperature=0.2` for deterministic
classification.

### Frontend — Debugbook

- **Metaphor.** Jupyter notebook. `In[n]:` / `Out[n]:` cell pairs,
  page titles like `auth.ipynb`, primary buttons labelled `▶ Run` and
  `▶ Analyze`.
- **CSS.** A single file at `style/main.css`, served via FastAPI's
  `StaticFiles` mount at `/style`.
- **Fonts.** Fira Code (monospace) + Space Grotesk (sans-serif), from
  Google Fonts CDN.
- **Animations.** GSAP for entrance staggers, status-badge pop-in,
  counter tick-ups, and meter-bar grow. All gated behind
  `gsap.matchMedia('(prefers-reduced-motion: no-preference)')`, so
  reduced-motion users get a fully visible static page.
- **Interactive history.** Live full-text search, status filter pills
  (all / SUCCESS / FAILED / PENDING) with running counts, and a sort
  toggle that persists via `localStorage`.
- **Code rendering.** Prism.js (1.29.0) syntax-highlights the submitted
  code with the language declared on the form. marked.js (13.0.3) +
  DOMPurify (3.1.6) renders the AI's recommendation as safe Markdown.

---

## Test suite

Run with:

```bash
.venv/bin/python -m pytest -q
```

Coverage:

| # | What it guards |
|---|---|
| 1 | Register success → 303 to `/login`, password stored hashed |
| 2 | Register duplicate username → 200 + error |
| 3 | Register duplicate email → 200 + error |
| 4 | Login success → sets session cookie, 303 to `/` |
| 5 | Login with bad credentials → 200 + error |
| 6 | Dashboard requires auth → 303 to `/login` if not authenticated |
| 7 | `/submit` requires auth → same redirect |
| 8 | Successful submit → row persisted, AI verdict rendered |
| 9 | Failed AI call → row persisted with the captured error |
| 10 | Multi-tenancy / IDOR — User A's data does NOT appear on User B's dashboard |
| 11 | Logout — cookie cleared, subsequent `/` redirects to `/login` |

Tests use in-memory SQLite with `StaticPool`, FastAPI's
`app.dependency_overrides[get_session]` for isolation, and
`monkeypatch.setattr(ai_service, "analyze_issue", ...)` so the real
Lightning AI is never called during the suite.

---

## Deployment

The app is ready for [Render](https://render.com) (or any platform
that runs a Python web service):

1. Push the repo to GitHub.
2. On Render: **New +** → **Web Service** → connect the repo.
3. Build command — `pip install uv && uv sync --frozen`
4. Start command — `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Set the four environment variables from the [Configuration](#configuration)
   section in Render's dashboard.

**Caveat:** Render's free tier filesystem is ephemeral, so the SQLite
database resets on every restart. For persistent storage, mount a
Render Disk and point `DATABASE_URL` in `app/database.py` inside the
mounted volume, or switch to Render's Postgres free tier.

---

## Security

- Passwords are bcrypt-hashed; the plaintext is never stored or
  logged.
- Session cookies are signed with `SECRET_KEY` and bound to
  `httponly` + `samesite=lax`. Flip `secure=True` for HTTPS.
- Jinja auto-escape is enabled for every `{{ }}`; the `|safe` filter
  is never applied to user-controlled data.
- AI Markdown is rendered only after passing through
  `DOMPurify.sanitize()`.
- Multi-tenant data isolation is enforced server-side. The IDOR test
  in the suite guards against accidental leaks.
- `.env` is gitignored and never enters version control.

---

## Author

**Omar Gamal ElKady**
AI Track · Intake 46 · Information Technology Institute (ITI)
Capstone project for the FastAPI course.
