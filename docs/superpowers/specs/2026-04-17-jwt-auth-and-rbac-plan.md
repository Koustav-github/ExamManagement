# JWT Auth + RBAC — Design & Workflow

**Date:** 2026-04-17
**Scope:** Add authenticated access to the FastAPI backend. Introduce access/refresh token auth, role-based authorization, and admin-only account creation. Out of scope: email flows, 2FA, rate limiting.

## 1. Decisions

| Area | Choice |
|---|---|
| Login endpoint | Unified `POST /auth/login`, body `{role, login_id, password}` |
| Tokens | Access + refresh — short access JWT (Bearer header), long refresh JWT (httpOnly cookie) |
| Account creation | Admin creates all — no public signup |
| Password hashing | `passlib[bcrypt]` |
| JWT library | `PyJWT` |
| Refresh revocation | `refresh_tokens` DB table, positive-list of valid `jti`; deleted on logout |
| Bootstrap | CLI seed script for first super_admin |

## 2. JWT claim shape

**Access** (15 min, `Authorization: Bearer`):
```
{ sub: <user_id:int>, role: "student"|"teacher"|"admin", type: "access", iat, exp }
```

**Refresh** (7 days, httpOnly `Secure` cookie):
```
{ sub, role, type: "refresh", jti: <uuid>, iat, exp }
```
`jti` persisted in `refresh_tokens`. Presence + not-expired + not-revoked = valid.

## 3. New surface area

### Dependencies
```
uv add pyjwt "passlib[bcrypt]" python-multipart
```

### Env vars
```
JWT_SECRET_KEY=<32 bytes hex — secrets.token_hex(32)>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

### Model addition (`models.py`)
`RefreshToken`: `id, jti (unique, indexed), user_id, role (str), expires_at, revoked (bool), created_at`. Polymorphic `user_id + role` — no FK, validated in app.

### New module files
- `auth.py` — `hash_password`, `verify_password`, `create_access_token`, `create_refresh_token`, `decode_token`. Pure, no DB, no FastAPI.
- `schemas.py` — Pydantic: `LoginRequest`, `LoginResponse`, `StudentCreate`, `TeacherCreate`, `AdminCreate`, `ChangePasswordRequest`, `UserInfo`.
- `deps.py` — FastAPI deps: `get_current_user`, `require_student`, `require_teacher`, `require_admin`, `require_super_admin`, `require_teacher_or_admin`.

### Routes

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/auth/login` | POST | none | Verify → access token + refresh cookie |
| `/auth/refresh` | POST | refresh cookie | Mint new access; optional refresh rotation |
| `/auth/logout` | POST | refresh cookie | Delete refresh row, clear cookie |
| `/auth/me` | GET | access token | Current user profile |
| `/auth/change-password` | POST | access token | Change own password |
| `/admin/students` | POST | admin | Create student |
| `/admin/teachers` | POST | admin | Create teacher |
| `/admin/admins` | POST | super_admin | Create admin |

Existing skeleton routes (`/student/signup`, `/teacher/signup`, etc.) are removed — replaced by admin-creates-all.

### Seed script
`backend/scripts/create_first_admin.py` — prompts, hashes, inserts first super_admin. Run once per environment.

## 4. Build order

1. Install deps and add env vars.
2. Add `RefreshToken` model → `alembic revision --autogenerate -m "add refresh_tokens"` → `alembic upgrade head`.
3. `auth.py` — hashing and token encode/decode, testable in isolation.
4. `schemas.py` — Pydantic types.
5. `deps.py` — `get_current_user` reads `role` claim, queries matching table, returns ORM row. 401 on any failure, 403 on wrong role.
6. Seed script, run once → first super_admin exists.
7. `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me` in `main.py`. Test login as seeded admin.
8. Admin-only creation routes. Create teacher and student as admin; login as each; verify `/auth/me`.
9. `/auth/change-password`.
10. (Next task, not this plan) Protect marks routes with role guards.

## 5. Gotchas

- Refresh cookie: `HttpOnly=true, Secure=true, SameSite=Lax, Path=/auth`.
- Login role check: if client sends `role=student` but `login_id` matches a teacher's `teacher_id`, reject outright.
- Timing attack mitigation on `/auth/login`: always run `verify_password` — against a throwaway hash if user not found — so response time doesn't leak whether the ID exists.
- Refresh rotation: if rotating on each `/auth/refresh`, revoke the old `jti` atomically.
- CORS: `allow_credentials=True` plus an explicit origin list (not `*`) so the refresh cookie works from browser frontends.

## 6. Out of scope

Email verification, password reset via email, 2FA, rate limiting on `/auth/login`, scoping teacher access by assigned classes.
