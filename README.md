# Academic Report Backend

FastAPI backend for the IEEE Entrance task. Admins provision students and
teachers; teachers upload marks for their assigned `(subject, class)` pairs;
students download their own report-card PDFs. Domain is academic reporting
(see [Domain reframe](#domain-reframe) at the bottom).

## Stack

- Python 3.12 + **FastAPI**
- **SQLAlchemy 2.x** + **Alembic**
- **Postgres** (Neon in prod, any Postgres locally)
- **PyJWT** access + refresh tokens, **bcrypt** password hashing
- **reportlab** for PDF generation
- **pytest** + `fastapi.testclient` for integration tests
- **uv** for dep + venv management

## Project layout

```
backend/
  main.py            # all routes
  models.py          # SQLAlchemy models + domain enums
  database.py        # engine + get_database dependency
  alembic/           # migrations
  tests/             # pytest
  .env.example       # copy to .env and fill in
  pyproject.toml
```

## Setup

From `backend/`:

```bash
uv sync                         # install deps
cp .env.example .env            # fill in real values
uv run alembic upgrade head     # apply migrations
uv run uvicorn main:app --reload
```

Seed a super-admin (one-off SQL or use a short script in `backend/scripts/`).
After that, sign in as that admin to create other users.

## Environment variables

All go in `backend/.env`. See `.env.example` for the canonical list.

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `JWT_SECRET_KEY` | HS256 signing secret — **change for prod** |
| `ALGORITHM` | JWT algorithm (`HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL (e.g. `15`) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL (e.g. `7`) |
| `SECURE_COOKIES` | `true` in prod (HTTPS only), `false` for local HTTP |
| `FRONTEND_ORIGIN` | Origin used once CORS is tightened (see note below) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | Mass-email sender (optional — the endpoint returns 503 if unset) |
| `TEST_DATABASE_URL` | Separate DB for `pytest`. **Never point at prod** — the suite drops the `public` schema on start |

## Running tests

```bash
TEST_DATABASE_URL="" \
  uv run pytest -v
```

Six test files covering auth, admin CRUD, marks sync, export, mass email,
report card, and delete cascades.

## API docs

- Swagger UI → https://academic-report-backend.onrender.com/docs
- ReDoc → https://academic-report-backend.onrender.com/redoc
- Raw OpenAPI → https://academic-report-backend.onrender.com/openapi.json
- Postman Collection -> https://koustaviitjee-9433383.postman.co/workspace/Marks-Registration~e3f94e6f-948b-4f18-b9ee-5517dace6d95/request/49164018-64a1ca96-e11e-41f8-afe3-3410b6887796?action=share&creator=49164018&active-environment=49164018-f1c1e38c-e7a9-46dc-ae93-de4d4a7af0d4

A Postman collection is produced by importing `openapi.json` directly.

## Features at a glance

- **Auth** — sign-in, refresh (JTI-rotated), logout
- **Admin dashboard** — create/list/filter/search/sort/paginate/delete for
  students; create/export/delete for teachers; super-admin creates admins
- **Data wrangling** — CSV + JSONL export (pandas-friendly), mass email
  driven by filters (server resolves recipients, client cannot inject addresses)
- **Teacher** — upload marks for authorized `(subject, class)` pairs,
  with a three-table in-transaction sync
- **Student** — download a styled PDF report card (= certificate generator
  per the brief's "more features" bullet)

## Design decisions

### CORS is intentionally wide open

```python
allow_origins=["*"], allow_credentials=True
```

This **should not** ship to prod. It's wide open because **the frontend
doesn't exist yet**; once a React (or whatever) client is in the repo, replace
`"*"` with `[FRONTEND_ORIGIN]` from the env var. A browser will silently
refuse credentialed requests against a wildcard origin — the refresh cookie
flow only works end-to-end once this is tightened.

### Admin-gated user provisioning (no public `/auth/signup`)

Students and teachers are created by an admin — there is no public signup
endpoint. This is the correct model for a school roster (people don't
self-enroll into classes). The admin-create routes run the same duplicate
check, password hash, and role assignment that a public signup would; only
the access control differs.

### Access token in memory, refresh in httpOnly cookie

Access tokens (15 min) are returned in the response body and expected to
live in client-side JS memory. Refresh tokens (7 days) live in an httpOnly
cookie scoped to `/auth`, unreachable from JS. Every `/auth/refresh` rotates
the JTI, so a stolen refresh cookie gets invalidated the next time the
legitimate user refreshes.

### Marks denormalized across three tables, synced in one transaction

`Marks` is the source of truth. `StudentSubject.marks` and
`TeacherSubjectStudent.marks` are cached copies for fast reads on the common
paths (report card and a teacher's view of their enrolled students).
`/teacher/marks` writes all three in one DB transaction. Never edit `Marks`
directly via SQL — the caches will drift.

### Enum names over values in the API

Class sections and subjects are `Enum` in Python. The API accepts enum
**names** (`ELEVEN_SC`, `PHYSICS`), not values (`"11th Grade Science"`). A
Pydantic `BeforeValidator` on `ClassLevelName` does the conversion. Display
labels can change without breaking payloads.

### Report card PDF = certificate generator

The brief's suggested "automatic certificate generator" is implemented as
`GET /student/report-card`: a styled PDF with name, class, per-subject
marks, total, and percentage — generated on demand via `reportlab`. QR
attendance and team-codes were evaluated and skipped — they don't fit an
academic roster domain where enrollment is already known.

## Domain reframe

The brief frames the task as "event management." This backend is framed
around academic reporting. The machinery is identical — auth, role-based
admin dashboard, data wrangling, bulk export, mass email. Reviewers who
want the event-management lens can read:

- `Students` → participants
- `Teachers` → organizers / judges
- `Admins` → event staff
- `class_section` → event / track
- `Marks` → scores / evaluations
- `/student/report-card` → participation certificate

## Acknowledgement

Built with **Claude** (Anthropic) as a pair-programming collaborator —
used for bouncing design decisions, scaffolding boilerplate, reviewing
edge cases, and drafting the test suite. Every line was reviewed,
edited, and accepted by me; the architectural calls (auth model, marks
denormalization, enum-name API, CORS posture, admin-gated provisioning)
are mine.
