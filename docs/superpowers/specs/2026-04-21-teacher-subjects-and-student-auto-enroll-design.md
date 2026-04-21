# Teacher Subject Scoping & Student Auto-Enrollment

**Date:** 2026-04-21
**Scope:** Scope each teacher to a set of `(subject, class_level)` pairs they're authorized to teach, and auto-populate `student_subjects` rows when a student is created. Out of scope: the marks endpoint itself — it consumes this data in a follow-up task.

## 1. Decisions

| Area | Choice |
|---|---|
| Teacher-subject model | New `TeacherSubject(teacher_id, subject, class_level)` link table |
| Granularity | Per `(subject, class_level)` — option (b). Math-for-grade-8 is distinct from Math-for-12th-SC. |
| Student subject source | Auto-populated from `SUBJECTS_BY_CLASS[class_section]` at `/admin/students` create time |
| Required on teacher create | ≥1 subject assignment |
| Existing teacher/student test rows | User deletes manually; no backfill path. No marks exist yet → safe. |

## 2. Schema

New model in `models.py`:

```python
class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "subject", "class_level",
            name="uq_teacher_subject_class",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(
        Integer,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject = Column(String, nullable=False)
    class_level = Column(Enum(ClassLevel), nullable=False)

    teacher = relationship("Teachers", back_populates="subjects")
```

Extend `Teachers`:

```python
subjects = relationship(
    "TeacherSubject", back_populates="teacher", cascade="all, delete-orphan"
)
```

## 3. Migration

`alembic revision --autogenerate -m "add teacher_subjects"` → `alembic upgrade head`.

**Gotcha:** the `classlevel` Postgres enum already exists (from `students.class_section`). If autogenerate emits `sa.Enum(..., name='classlevel')` inside `op.create_table` it will try to `CREATE TYPE` again and fail. If so, hand-edit to use `postgresql.ENUM(name='classlevel', create_type=False)` referencing the existing type.

## 4. API changes (`main.py`)

### New pydantic model

```python
class TeacherSubjectAssignment(BaseModel):
    subject: str                      # enum name: "MATH", "PHYSICS", ...
    class_level: models.ClassLevel    # enum name: "EIGHT", "ELEVEN_SC", ...
```

### `TeacherCreate` gains

```python
subjects: list[TeacherSubjectAssignment] = Field(min_length=1)
```

### `POST /admin/teachers`

1. For each item in `payload.subjects`: `models.valid_subject_for_class(item.class_level, item.subject)` — if any False, `HTTPException(400, "invalid subject '<s>' for class '<c>'")`.
2. Build `Teachers` row.
3. Append one `TeacherSubject` per assignment (either via `teacher.subjects = [...]` before add, or `db.add()` each after).
4. Single `db.commit()`. `IntegrityError` → 409 (covers duplicate teacher_id/email *and* duplicate `(teacher_id, subject, class_level)` triple).
5. Response adds `"subjects": [{"subject": ..., "class_level": ...}, ...]`.

### `POST /admin/students`

After building the `Students` instance and before commit, iterate `SUBJECTS_BY_CLASS[payload.class_section].__members__.keys()` and attach one `StudentSubject(subject=name)` per member to `student.subjects`. Single transaction. Rollback rolls back both.

Response optionally adds `"subjects": [<enum-name>, ...]`.

## 5. Payload examples

Teacher create:
```json
{
  "name": "Ms. Priya",
  "teacher_id": "T001",
  "email": "priya@school.edu",
  "mobile_number": "9876543210",
  "password": "secret123",
  "subjects": [
    {"subject": "MATH",    "class_level": "EIGHT"},
    {"subject": "MATH",    "class_level": "NINE"},
    {"subject": "PHYSICS", "class_level": "ELEVEN_SC"}
  ]
}
```

Student create — payload unchanged, `student_subjects` rows appear post-create:
```json
{
  "name": "Aarav",
  "school_id": "S123",
  "email": "aarav@school.edu",
  "mobile_number": "9123456789",
  "password": "secret123",
  "class_section": "ELEVEN_SC"
}
```

## 6. Future enforcement (not this spec)

Marks endpoint must verify `(teacher.id, marks.subject, student.class_section)` matches a `TeacherSubject` row. This design only prepares the table; enforcement is the next task.

## 7. Build order

1. Add `TeacherSubject` + `Teachers.subjects` in `models.py`.
2. `alembic revision --autogenerate` → inspect/patch enum reuse → `alembic upgrade head`.
3. Add `TeacherSubjectAssignment`, extend `TeacherCreate`.
4. Update `/admin/teachers`: validate pairs, insert teacher + subjects, 400/409 paths.
5. Update `/admin/students`: auto-insert `StudentSubject` rows from `SUBJECTS_BY_CLASS`.
6. User deletes pre-change test teacher/student rows.
7. End-to-end Postman: admin → create teacher with subjects → create student → verify both rows + link rows exist.

## 8. Gotchas

- `classlevel` enum reuse (see §3).
- Duplicate subject triples within a single admin call → single `IntegrityError`, whole teacher rolls back. 409 message should say "duplicate subject assignment".
- `TeacherSubject` stores `subject` as String (enum name), matching how `StudentSubject` and `Marks` already do. Keeps the three tables keyable on the same string.
- No admin UI for editing a teacher's subjects post-create yet — recreate the teacher if assignments change.
