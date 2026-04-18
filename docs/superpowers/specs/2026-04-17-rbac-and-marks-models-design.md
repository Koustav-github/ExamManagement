# RBAC Tables, Subjects, and Marks — `backend/models.py`

**Date:** 2026-04-17
**Scope:** Complete the SQLAlchemy model layer in `backend/models.py`. Out of scope: auth routes, password hashing utilities, marks CRUD routes, migrations.

## Goals

1. Three RBAC tables — `students`, `teachers`, `admins` — each with role implicit in table membership and each identified by a school-issued login handle plus a password hash.
2. Students enroll in subjects drawn from a stream-specific enum determined by their `class_section`. Classes 8/9/10 have a fixed core curriculum (no per-student enrollment row).
3. A single `marks` table records one row per `(student, subject)` for one term exam, with max marks, obtained marks, and a teacher audit FK.
4. Access control (student sees only own marks, teacher sees all) is enforced at the FastAPI route layer, not at the ORM layer — the models must only support the required queries cleanly.

## Tables

### `students`
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| name | String | not null |
| school_id | String | unique, indexed, login handle |
| email_id | String | unique, indexed |
| mobile_number | String | |
| password_hash | String | bcrypt/argon2, set by the auth layer |
| class_section | Enum(ClassLevel) | drives valid subject set |
| created_at | DateTime(tz) | server default `now()` |

### `teachers`
Same shape as students, minus `class_section`, with `teacher_id` replacing `school_id`.

### `admins`
Same shape as teachers, with `admin_id` replacing `teacher_id`, plus `super_admin: Boolean` (default false).

### `student_subjects` (link table — 11th/12th only)
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| student_id | FK students.id | ON DELETE CASCADE, indexed |
| subject | String | stores the Python enum `.name` |

Unique constraint on `(student_id, subject)`. Rows only inserted when `class_section` is an 11th/12th stream.

### `marks`
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| student_id | FK students.id | ON DELETE CASCADE, indexed |
| subject | String | stores enum `.name` |
| max_marks | Float | not null |
| marks_obtained | Float | not null |
| entered_by_teacher_id | FK teachers.id | ON DELETE SET NULL, nullable for data retention if teacher removed |
| created_at | DateTime(tz) | server default `now()` |

Unique constraint on `(student_id, subject)` — one row per subject per student (single term exam).

## Enums

- `ClassLevel` (existing, normalized casing — `TWELVE_SC` instead of `TWELVE_sc`)
- `CoreSubject` — 8th/9th/10th reference list: MATH, SCIENCE, SOCIAL_SCIENCE, ENGLISH, HINDI, BENGALI, COMPUTER
- `ScienceSubject` — PHYSICS, CHEMISTRY, MATH, BIOLOGY, COMPUTER_SCIENCE, ENGLISH
- `CommerceSubject` — ACCOUNTANCY, BUSINESS_STUDIES, ECONOMICS, MATH, ENGLISH, COMPUTER_APPLICATIONS
- `ArtsSubject` — HISTORY, GEOGRAPHY, POLITICAL_SCIENCE, ECONOMICS, ENGLISH, SOCIOLOGY

A module-level `SUBJECTS_BY_CLASS: dict[ClassLevel, type[enum.Enum]]` maps each class level to its valid subject enum. A `valid_subject_for_class(class_level, subject_name) -> bool` helper uses this map so the route layer can validate incoming subject strings before insert.

## Why VARCHAR + Python validation for `subject`?

A DB-level enum column can't vary its valid set per row. Since the valid subject set depends on the row's `class_section`, we store the subject `.name` as VARCHAR and validate in Python using `SUBJECTS_BY_CLASS`. This preserves correctness while keeping the schema simple.

## Access control (routes — not in models)

- JWT carries `sub` (user id) and `role` (`student` | `teacher` | `admin`).
- `GET /marks/me` → student-only; filter `Marks.student_id == current_user.id`.
- `GET /students/{id}/marks` → teacher/admin only.
- `POST /marks` and `PUT /marks/{id}` → teacher/admin only; server sets `entered_by_teacher_id` from JWT.
- Admin routes for CRUD on all three role tables — admin/super_admin only.

Models don't enforce these rules; they only need to make the queries efficient (indexed FKs on `student_id` and `entered_by_teacher_id`).

## Relationships

- `Students.subjects` → `StudentSubject` (one-to-many, cascade delete)
- `Students.marks` → `Marks` (one-to-many, cascade delete)
- `Marks.entered_by` → `Teachers` (many-to-one)
- `Teachers.marks_entered` → `Marks` (one-to-many)

No relationship between admins and other tables — admins operate via routes, not foreign keys.

## Non-goals

- No password-hashing helper (auth module's job).
- No Alembic migration generated here (done separately).
- No Pydantic schemas (added alongside routes).
- No seed data.
