from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import get_database
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import bcrypt
import csv
import io
import json
import jwt
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, EmailStr, Field
import models
import os
from dotenv import load_dotenv

load_dotenv()

openapi_tags = [
    {
        "name": "Auth",
        "description": (
            "Sign in, refresh access tokens, log out. "
            "Access tokens live 15 min; refresh tokens live 7 days in an "
            "httpOnly cookie scoped to `/auth`, rotated on every refresh."
        ),
    },
    {
        "name": "Admin - Students",
        "description": (
            "Create, list, export, and email students. Admin role required. "
            "Students are auto-enrolled in their class's subjects on creation."
        ),
    },
    {
        "name": "Admin - Teachers",
        "description": (
            "Create and export teachers with their (subject, class) "
            "assignments. Admin role required."
        ),
    },
    {
        "name": "Admin - Admins",
        "description": "Super-admin only. Create additional admin accounts.",
    },
    {
        "name": "Teacher",
        "description": (
            "Teacher-scoped actions. Marks upload is authorized only for "
            "(subject, class) pairs the teacher is assigned to."
        ),
    },
    {
        "name": "Student",
        "description": "Student self-service. Download a styled report-card PDF.",
    },
]


app = FastAPI(
    title="Academic Report Backend",
    version="1.0.0",
    description=(
        "Backend for an academic reporting system.\n\n"
        "**Roles**\n"
        "- **Admin** — manages students, teachers, and other admins. "
        "Super-admins can create other admins.\n"
        "- **Teacher** — uploads marks for students in their assigned "
        "(subject, class) pairs.\n"
        "- **Student** — downloads their own report card.\n\n"
        "**Auth model** — JWT bearer access tokens returned in the response "
        "body; refresh tokens stored in an httpOnly cookie scoped to `/auth` "
        "with JTI rotation on every refresh.\n\n"
        "**Data wrangling** — the admin dashboard supports search, filter, "
        "sort, pagination, bulk CSV/JSON export (students + teachers), and "
        "filter-driven mass email."
    ),
    openapi_tags=openapi_tags,
    contact={"name": "IEEE Entrance — Academic Report"},
)

SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reused on every failed lookup so response time doesn't leak whether the id exists.
DUMMY_HASH = bcrypt.hashpw(
    b"dummy-password-for-timing-defense", bcrypt.gensalt()
).decode("utf-8")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


class UserSync(BaseModel):
    email: EmailStr = Field(examples=["alice@school.edu"])
    password: str = Field(min_length=1, max_length=72, examples=["s3cret!"])
    role: models.Role = Field(examples=["student"])


class LoginResponse(BaseModel):
    access_token: str = Field(
        description="JWT bearer token. Lifetime matches `expires_in`.",
        examples=["eyJhbGciOiJIUzI1NiIs..."],
    )
    token_type: str = "bearer"
    expires_in: int = Field(
        description="Access token lifetime in seconds.", examples=[900]
    )

secret_key = os.getenv("JWT_SECRET_KEY")
algorithm = os.getenv("ALGORITHM")
access_time = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
refresh_time = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"))

def create_access_token(sub: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload ={
        "sub": str(sub),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=access_time),
    }

    return jwt.encode(payload, secret_key, algorithm=algorithm)

def create_refresh_token(sub: int, role: str) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=refresh_time)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(sub),
        "role": role,
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    return token, jti, exp
    

@app.post(
    "/user/signin",
    response_model=LoginResponse,
    tags=["Auth"],
    summary="Sign in with email + password + role",
    description=(
        "Verifies credentials against the role's table and returns an access "
        "token in the body plus a refresh cookie (`refresh_token`, httpOnly, "
        "path=`/auth`). Store the access token in memory on the client; the "
        "refresh cookie is handled by the browser.\n\n"
        "**One active session at a time.** If a valid refresh cookie is "
        "already present (any role), the request is rejected with 409. Call "
        "`POST /auth/logout` first, then sign in again — switching roles in "
        "the same browser requires an explicit logout."
    ),
    responses={
        401: {"description": "Invalid email or password"},
        409: {"description": "Already signed in — call /auth/logout first"},
    },
)
def sync_user(
    user_data: UserSync,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_database),
):
    if refresh_token:
        try:
            existing = jwt.decode(
                refresh_token, secret_key, algorithms=[algorithm]
            )
            if existing.get("type") == "refresh":
                prev_sub = int(existing["sub"])
                prev_role = models.Role(existing["role"])
                prev_jti = existing["jti"]
                if prev_role is models.Role.STUDENT:
                    prev = db.get(models.Students, prev_sub)
                elif prev_role is models.Role.TEACHER:
                    prev = db.get(models.Teachers, prev_sub)
                elif prev_role is models.Role.ADMIN:
                    prev = db.get(models.Admins, prev_sub)
                else:
                    prev = None
                if prev is not None and prev.refresh_jti == prev_jti:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "already signed in — call /auth/logout first",
                    )
        except HTTPException:
            raise
        except (jwt.InvalidTokenError, KeyError, ValueError):
            pass

    user = None
    if user_data.role is models.Role.STUDENT:
        user = (
            db.query(models.Students)
            .filter(models.Students.email_id == user_data.email)
            .first()
        )
    if user_data.role is models.Role.TEACHER:
        user = (
            db.query(models.Teachers)
            .filter(models.Teachers.email_id == user_data.email)
            .first()
        )
    if user_data.role is models.Role.ADMIN:
        user = (
            db.query(models.Admins)
            .filter(models.Admins.email_id == user_data.email)
            .first()
        )

    if user is None:
        verify_password(user_data.password, DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    access = create_access_token(sub=user.id, role=user.role.value)
    refresh, jti, exp = create_refresh_token(sub=user.id, role=user.role.value)

    user.refresh_jti = jti
    user.refresh_expires_at = exp
    db.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=refresh_time * 24 * 60 * 60,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/auth",
    )

    return LoginResponse(
        access_token=access,
        expires_in=access_time * 60,
    )

@app.post(
    "/auth/refresh",
    response_model=LoginResponse,
    tags=["Auth"],
    summary="Rotate refresh token and mint a new access token",
    description=(
        "Reads the `refresh_token` cookie, verifies its JTI against the "
        "server-side record, then issues a **new** access token and a new "
        "refresh cookie with a rotated JTI. Use this when your access token "
        "expires so the user doesn't have to log in again."
    ),
    responses={401: {"description": "Missing, invalid, or revoked refresh token"}},
)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_database),
):
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no refresh token")

    try:
        payload = jwt.decode(refresh_token, secret_key, algorithms=[algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not a refresh token")

    try:
        sub = int(payload["sub"])
        role = models.Role(payload["role"])
        jti = payload["jti"]
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed refresh token")

    if role is models.Role.STUDENT:
        user = db.get(models.Students, sub)
    elif role is models.Role.TEACHER:
        user = db.get(models.Teachers, sub)
    elif role is models.Role.ADMIN:
        user = db.get(models.Admins, sub)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid role")

    if user is None or user.refresh_jti != jti:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token revoked")

    new_access = create_access_token(sub=user.id, role=user.role.value)
    new_refresh, new_jti, new_exp = create_refresh_token(
        sub=user.id, role=user.role.value
    )

    user.refresh_jti = new_jti
    user.refresh_expires_at = new_exp
    db.commit()

    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        max_age=refresh_time * 24 * 60 * 60,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/auth",
    )

    return LoginResponse(
        access_token=new_access,
        expires_in=access_time * 60,
    )


@app.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Auth"],
    summary="Revoke refresh token and clear the cookie",
    description=(
        "Idempotent. Clears the `refresh_token` cookie and, if a valid token "
        "is present, nulls the server-side JTI so the token can't be reused."
    ),
)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_database),
):
    response.delete_cookie("refresh_token", path="/auth")

    if not refresh_token:
        return

    try:
        payload = jwt.decode(refresh_token, secret_key, algorithms=[algorithm])
    except jwt.InvalidTokenError:
        return

    if payload.get("type") != "refresh":
        return

    try:
        sub = int(payload["sub"])
        role = models.Role(payload["role"])
        jti = payload["jti"]
    except (KeyError, ValueError):
        return

    if role is models.Role.STUDENT:
        user = db.get(models.Students, sub)
    elif role is models.Role.TEACHER:
        user = db.get(models.Teachers, sub)
    elif role is models.Role.ADMIN:
        user = db.get(models.Admins, sub)
    else:
        return

    if user is None or user.refresh_jti != jti:
        return

    user.refresh_jti = None
    user.refresh_expires_at = None
    db.commit()


bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_database),
):
    try:
        payload = jwt.decode(
            credentials.credentials, secret_key, algorithms=[algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not an access token")

    try:
        sub = int(payload["sub"])
        role = models.Role(payload["role"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token")

    if role is models.Role.STUDENT:
        user = db.get(models.Students, sub)
    elif role is models.Role.TEACHER:
        user = db.get(models.Teachers, sub)
    elif role is models.Role.ADMIN:
        user = db.get(models.Admins, sub)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid role")

    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")

    return user


def require_admin(user=Depends(get_current_user)):
    if user.role is not models.Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def require_super_admin(admin=Depends(require_admin)):
    if not admin.super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "super admin only")
    return admin


def require_teacher(user=Depends(get_current_user)):
    if user.role is not models.Role.TEACHER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "teacher only")
    return user


def require_student(user=Depends(get_current_user)):
    if user.role is not models.Role.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "student only")
    return user


def _class_level_from_name(v):
    if isinstance(v, models.ClassLevel):
        return v
    # Try to get by Name (Key)
    try:
        return models.ClassLevel[v]
    except KeyError:
        # Try to get by Value (Label)
        for member in models.ClassLevel:
            if member.value == v:
                return member
    raise ValueError(f"Invalid class level '{v}'")


ClassLevelName = Annotated[models.ClassLevel, BeforeValidator(_class_level_from_name)]


class StudentCreate(BaseModel):
    name: str = Field(examples=["Alice Rao"])
    school_id: str = Field(
        description="Unique school roll / admission number.",
        examples=["S001"],
    )
    email: EmailStr = Field(examples=["alice@school.edu"])
    mobile_number: str = Field(examples=["9876543210"])
    password: str = Field(min_length=1, max_length=72, examples=["alice-pass"])
    class_section: ClassLevelName = Field(
        description=(
            "Enum **name**, not label. Pass `ELEVEN_SC`, not "
            "`'11th Grade Science'`. Auto-determines the subject list the "
            "student gets enrolled in."
        ),
        examples=["ELEVEN_SC"],
    )


class TeacherSubjectAssignment(BaseModel):
    subject: str = Field(
        description=(
            "Subject enum **name** matching the class's subject group "
            "(e.g. `PHYSICS` for a Science class)."
        ),
        examples=["PHYSICS"],
    )
    class_level: ClassLevelName = Field(examples=["ELEVEN_SC"])


class TeacherCreate(BaseModel):
    name: str = Field(examples=["Bob Mehta"])
    teacher_id: str = Field(examples=["T001"])
    email: EmailStr = Field(examples=["bob@school.edu"])
    mobile_number: str = Field(examples=["9123456780"])
    password: str = Field(min_length=1, max_length=72, examples=["bob-pass"])
    subjects: list[TeacherSubjectAssignment] = Field(
        min_length=1,
        description=(
            "One or more (subject, class_level) pairs the teacher will own. "
            "Duplicate pairs are rejected with 409."
        ),
    )


class AdminCreate(BaseModel):
    name: str = Field(examples=["Carla Admin"])
    admin_id: str = Field(examples=["A001"])
    email: EmailStr = Field(examples=["carla@school.edu"])
    mobile_number: str = Field(examples=["9000000000"])
    password: str = Field(min_length=1, max_length=72, examples=["carla-pass"])
    super_admin: bool = Field(
        default=False,
        description="If true, this admin can create other admins.",
    )


class MarksUpload(BaseModel):
    student_id: int = Field(examples=[42])
    subject: str = Field(
        description="Subject enum name, e.g. `PHYSICS`.",
        examples=["PHYSICS"],
    )
    max_marks: float = Field(
        gt=0, description="Total marks for the assessment.", examples=[100]
    )
    marks_obtained: float = Field(
        ge=0,
        description="Must not exceed `max_marks`. Server returns 400 if it does.",
        examples=[87],
    )


@app.post(
    "/admin/students",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Students"],
    summary="Create a student and auto-enroll in class subjects",
    description=(
        "Creates the student row, then auto-creates `StudentSubject` rows for "
        "every subject in the class's subject group (Science, Commerce, Arts, "
        "or Core). Also back-links the student to every existing `TeacherSubject` "
        "that matches their (class, subject) so teachers immediately see them."
    ),
    responses={
        409: {"description": "school_id or email already exists"},
        403: {"description": "Caller is not an admin"},
    },
)
def create_student(
    payload: StudentCreate,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    student = models.Students(
        name=payload.name,
        school_id=payload.school_id,
        email_id=payload.email,
        mobile_number=payload.mobile_number,
        password_hash=hash_password(payload.password),
        class_section=payload.class_section,
    )
    subject_enum = models.SUBJECTS_BY_CLASS[payload.class_section]
    subject_names = list(subject_enum.__members__.keys())
    student.subjects = [
        models.StudentSubject(subject=name) for name in subject_names
    ]
    db.add(student)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "school_id or email already exists"
        )

    matching_ts = (
        db.query(models.TeacherSubject)
        .filter(
            models.TeacherSubject.class_level == payload.class_section,
            models.TeacherSubject.subject.in_(subject_names),
        )
        .all()
    )
    for ts in matching_ts:
        db.add(
            models.TeacherSubjectStudent(
                teacher_subject_id=ts.id, student_id=student.id
            )
        )

    db.commit()
    db.refresh(student)
    return {
        "id": student.id,
        "school_id": student.school_id,
        "email": student.email_id,
        "role": student.role.value,
        "subjects": [
            {"subject": s.subject, "marks": s.marks} for s in student.subjects
        ],
    }


STUDENT_SORT_FIELDS = {
    "id": models.Students.id,
    "name": models.Students.name,
    "school_id": models.Students.school_id,
    "email": models.Students.email_id,
    "created_at": models.Students.created_at,
}


@app.get(
    "/admin/students",
    tags=["Admin - Students"],
    summary="List students with search / filter / sort / pagination",
    description=(
        "The core data-wrangling endpoint. Combine `search`, `class_section`, "
        "`sort_by`, `order`, `page`, and `page_size` to slice the student list. "
        "`sort_by` is a strict whitelist (no SQL injection via column name)."
    ),
)
def list_students(
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
    search: str | None = Query(
        None, description="case-insensitive substring match on name/school_id/email"
    ),
    class_section: str | None = Query(
        None, description="enum name, e.g. ELEVEN_SC"
    ),
    sort_by: str = Query("name"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    if sort_by not in STUDENT_SORT_FIELDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"sort_by must be one of {list(STUDENT_SORT_FIELDS)}",
        )

    q = db.query(models.Students)

    if class_section is not None:
        if class_section not in models.ClassLevel.__members__:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"invalid class_section '{class_section}'",
            )
        q = q.filter(
            models.Students.class_section == models.ClassLevel[class_section]
        )

    if search:
        like = f"%{search}%"
        q = q.filter(
            (models.Students.name.ilike(like))
            | (models.Students.school_id.ilike(like))
            | (models.Students.email_id.ilike(like))
        )

    total = q.count()

    sort_col = STUDENT_SORT_FIELDS[sort_by]
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    q = q.offset((page - 1) * page_size).limit(page_size)

    rows = q.all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "school_id": s.school_id,
                "email": s.email_id,
                "mobile_number": s.mobile_number,
                "class_section": s.class_section.name,
                "created_at": s.created_at.isoformat(),
            }
            for s in rows
        ],
    }


@app.delete(
    "/admin/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Students"],
    summary="Delete a student and all their enrollments / marks",
    description=(
        "Removes the student row. FK cascades clean up `StudentSubject`, "
        "`TeacherSubjectStudent`, and `Marks`. Irreversible — no soft delete."
    ),
    responses={
        404: {"description": "Student not found"},
        403: {"description": "Caller is not an admin"},
    },
)
def delete_student(
    student_id: int,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    student = db.get(models.Students, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "student not found")
    db.delete(student)
    db.commit()


@app.post(
    "/admin/teachers",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Teachers"],
    summary="Create a teacher with one or more (subject, class) assignments",
    description=(
        "Each `(subject, class_level)` pair is validated against the class's "
        "subject group (e.g. `HISTORY` at `ELEVEN_SC` is rejected with 400). "
        "After creation, the teacher is linked to every student currently "
        "enrolled in those (subject, class) pairs."
    ),
    responses={
        400: {"description": "Invalid subject for a class in the assignment list"},
        409: {"description": "teacher_id/email duplicate or duplicate assignment"},
        403: {"description": "Caller is not an admin"},
    },
)
def create_teacher(
    payload: TeacherCreate,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    for item in payload.subjects:
        if not models.valid_subject_for_class(item.class_level, item.subject):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"invalid subject '{item.subject}' for class '{item.class_level.name}'",
            )

    teacher = models.Teachers(
        name=payload.name,
        teacher_id=payload.teacher_id,
        email_id=payload.email,
        mobile_number=payload.mobile_number,
        password_hash=hash_password(payload.password),
    )
    teacher.subjects = [
        models.TeacherSubject(subject=item.subject, class_level=item.class_level)
        for item in payload.subjects
    ]
    db.add(teacher)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "teacher_id/email already exists or duplicate subject assignment",
        )

    for ts in teacher.subjects:
        matching_students = (
            db.query(models.Students)
            .join(models.StudentSubject)
            .filter(
                models.Students.class_section == ts.class_level,
                models.StudentSubject.subject == ts.subject,
            )
            .all()
        )
        for s in matching_students:
            db.add(
                models.TeacherSubjectStudent(
                    teacher_subject_id=ts.id, student_id=s.id
                )
            )

    db.commit()
    db.refresh(teacher)
    return {
        "id": teacher.id,
        "teacher_id": teacher.teacher_id,
        "email": teacher.email_id,
        "role": teacher.role.value,
        "subjects": [
            {
                "subject": s.subject,
                "class_level": s.class_level.name,
                "students_enrolled": len(s.students),
            }
            for s in teacher.subjects
        ],
    }


@app.delete(
    "/admin/teachers/{teacher_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Teachers"],
    summary="Delete a teacher and their subject assignments",
    description=(
        "Removes the teacher row. FK cascades clean up `TeacherSubject` and "
        "`TeacherSubjectStudent`. `Marks` rows entered by this teacher are "
        "preserved — `Marks.entered_by_teacher_id` becomes NULL. "
        "Path param is the numeric PK, not the school `teacher_id` string."
    ),
    responses={
        404: {"description": "Teacher not found"},
        403: {"description": "Caller is not an admin"},
    },
)
def delete_teacher(
    teacher_id: int,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    teacher = db.get(models.Teachers, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "teacher not found")
    db.delete(teacher)
    db.commit()


@app.post(
    "/admin/admins",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Admins"],
    summary="Create a new admin (super-admin only)",
    description=(
        "Only a caller whose JWT belongs to an admin with `super_admin=True` "
        "may create other admins. Use `super_admin: true` in the body to "
        "grant the new admin this same privilege."
    ),
    responses={
        409: {"description": "admin_id or email already exists"},
        403: {"description": "Caller is not a super-admin"},
    },
)
def create_admin(
    payload: AdminCreate,
    _super=Depends(require_super_admin),
    db: Session = Depends(get_database),
):
    new_admin = models.Admins(
        name=payload.name,
        admin_id=payload.admin_id,
        email_id=payload.email,
        mobile_number=payload.mobile_number,
        password_hash=hash_password(payload.password),
        super_admin=payload.super_admin,
    )
    db.add(new_admin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "admin_id or email already exists"
        )
    db.refresh(new_admin)
    return {
        "id": new_admin.id,
        "admin_id": new_admin.admin_id,
        "email": new_admin.email_id,
        "role": new_admin.role.value,
        "super_admin": new_admin.super_admin,
    }


@app.post(
    "/teacher/marks",
    tags=["Teacher"],
    summary="Upload (or update) a student's marks for an authorized subject",
    description=(
        "Upserts the `Marks` row for `(student_id, subject)` and keeps the "
        "denormalized copies (`StudentSubject.marks` and "
        "`TeacherSubjectStudent.marks`) in sync — all in one transaction. "
        "The caller must own a matching `TeacherSubject` row for the "
        "student's class, otherwise 403."
    ),
    responses={
        400: {"description": "marks_obtained exceeds max_marks"},
        403: {"description": "Teacher not authorized for this subject/class"},
        404: {"description": "Student not found"},
    },
)
def upload_marks(
    payload: MarksUpload,
    teacher=Depends(require_teacher),
    db: Session = Depends(get_database),
):
    if payload.marks_obtained > payload.max_marks:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "marks_obtained cannot exceed max_marks",
        )

    student = db.get(models.Students, payload.student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "student not found")

    ts = (
        db.query(models.TeacherSubject)
        .filter(
            models.TeacherSubject.teacher_id == teacher.id,
            models.TeacherSubject.subject == payload.subject,
            models.TeacherSubject.class_level == student.class_section,
        )
        .first()
    )
    if ts is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "teacher not authorized for this subject/class",
        )

    tss = (
        db.query(models.TeacherSubjectStudent)
        .filter(
            models.TeacherSubjectStudent.teacher_subject_id == ts.id,
            models.TeacherSubjectStudent.student_id == payload.student_id,
        )
        .first()
    )
    if tss is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "student not enrolled under this teacher's subject",
        )

    mark = (
        db.query(models.Marks)
        .filter(
            models.Marks.student_id == payload.student_id,
            models.Marks.subject == payload.subject,
        )
        .first()
    )
    if mark is None:
        mark = models.Marks(
            student_id=payload.student_id,
            subject=payload.subject,
            max_marks=payload.max_marks,
            marks_obtained=payload.marks_obtained,
            entered_by_teacher_id=teacher.id,
        )
        db.add(mark)
    else:
        mark.max_marks = payload.max_marks
        mark.marks_obtained = payload.marks_obtained
        mark.entered_by_teacher_id = teacher.id

    tss.marks = payload.marks_obtained

    ss = (
        db.query(models.StudentSubject)
        .filter(
            models.StudentSubject.student_id == payload.student_id,
            models.StudentSubject.subject == payload.subject,
        )
        .first()
    )
    if ss is not None:
        ss.marks = payload.marks_obtained

    db.commit()
    db.refresh(mark)
    return {
        "id": mark.id,
        "student_id": mark.student_id,
        "subject": mark.subject,
        "max_marks": mark.max_marks,
        "marks_obtained": mark.marks_obtained,
        "entered_by_teacher_id": mark.entered_by_teacher_id,
    }


def _filtered_students_query(
    db: Session, search: str | None, class_section: str | None
):
    q = db.query(models.Students)
    if class_section is not None:
        if class_section not in models.ClassLevel.__members__:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"invalid class_section '{class_section}'",
            )
        q = q.filter(
            models.Students.class_section == models.ClassLevel[class_section]
        )
    if search:
        like = f"%{search}%"
        q = q.filter(
            (models.Students.name.ilike(like))
            | (models.Students.school_id.ilike(like))
            | (models.Students.email_id.ilike(like))
        )
    return q


STUDENT_EXPORT_COLUMNS = [
    "student_id",
    "name",
    "school_id",
    "email",
    "class_section",
    "subject",
    "marks",
]


def _student_rows(students):
    for s in students:
        for sub in s.subjects:
            yield {
                "student_id": s.id,
                "name": s.name,
                "school_id": s.school_id,
                "email": s.email_id,
                "class_section": s.class_section.name,
                "subject": sub.subject,
                "marks": sub.marks,
            }


@app.get(
    "/admin/students/export",
    tags=["Admin - Students"],
    summary="Export student marks as CSV or JSON (long format)",
    description=(
        "Streams every `(student, subject, marks)` row matching the filters. "
        "Pivotable in pandas via `df.pivot_table(index='name', "
        "columns='subject', values='marks')`. CSV opens directly in Google "
        "Sheets / Excel; JSON is newline-delimited (JSONL / NDJSON)."
    ),
    response_class=StreamingResponse,
)
def export_students(
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
    search: str | None = Query(None),
    class_section: str | None = Query(None),
    format: str = Query("csv", pattern="^(csv|json)$"),
):
    students = _filtered_students_query(db, search, class_section).all()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "json":
        def gen_json():
            for row in _student_rows(students):
                yield json.dumps(row) + "\n"
        return StreamingResponse(
            gen_json(),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="students-{stamp}.jsonl"'
            },
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=STUDENT_EXPORT_COLUMNS)
    writer.writeheader()
    for row in _student_rows(students):
        writer.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="students-{stamp}.csv"'
        },
    )


TEACHER_EXPORT_COLUMNS = ["teacher_id", "name", "email", "subject", "class_level"]


def _filtered_teacher_subjects(
    db: Session,
    search: str | None,
    subject: str | None,
    class_level: str | None,
):
    q = (
        db.query(models.TeacherSubject)
        .join(models.Teachers, models.TeacherSubject.teacher_id == models.Teachers.id)
    )
    if class_level is not None:
        if class_level not in models.ClassLevel.__members__:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"invalid class_level '{class_level}'"
            )
        q = q.filter(
            models.TeacherSubject.class_level == models.ClassLevel[class_level]
        )
    if subject is not None:
        q = q.filter(models.TeacherSubject.subject == subject)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (models.Teachers.name.ilike(like))
            | (models.Teachers.teacher_id.ilike(like))
            | (models.Teachers.email_id.ilike(like))
        )
    return q


def _teacher_rows(teacher_subjects):
    for ts in teacher_subjects:
        yield {
            "teacher_id": ts.teacher.teacher_id,
            "name": ts.teacher.name,
            "email": ts.teacher.email_id,
            "subject": ts.subject,
            "class_level": ts.class_level.name,
        }


@app.get(
    "/admin/teachers/export",
    tags=["Admin - Teachers"],
    summary="Export teacher assignments as CSV or JSON",
    description=(
        "One row per `(teacher, subject, class_level)` assignment. A teacher "
        "with 3 assignments produces 3 rows. Filter by `search` (teacher "
        "name/id/email), `subject`, or `class_level`."
    ),
    response_class=StreamingResponse,
)
def export_teachers(
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
    search: str | None = Query(None),
    subject: str | None = Query(None),
    class_level: str | None = Query(None),
    format: str = Query("csv", pattern="^(csv|json)$"),
):
    rows = _filtered_teacher_subjects(db, search, subject, class_level).all()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "json":
        def gen_json():
            for row in _teacher_rows(rows):
                yield json.dumps(row) + "\n"
        return StreamingResponse(
            gen_json(),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="teachers-{stamp}.jsonl"'
            },
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TEACHER_EXPORT_COLUMNS)
    writer.writeheader()
    for row in _teacher_rows(rows):
        writer.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="teachers-{stamp}.csv"'
        },
    )


class EmailFilters(BaseModel):
    search: str | None = Field(
        default=None,
        description="Substring match on name/school_id/email.",
        examples=["alice"],
    )
    class_section: str | None = Field(
        default=None,
        description="Class enum name, e.g. `ELEVEN_SC`.",
        examples=["ELEVEN_SC"],
    )


class MassEmail(BaseModel):
    subject: str = Field(
        min_length=1, max_length=200, examples=["Mid-term results"]
    )
    body: str = Field(
        min_length=1,
        examples=["Your mid-term results have been posted. Log in to view."],
    )
    filters: EmailFilters = Field(
        default_factory=EmailFilters,
        description=(
            "Recipients are derived server-side from these filters — "
            "the client cannot email arbitrary addresses."
        ),
    )


class MassEmailResponse(BaseModel):
    recipients_matched: int
    sent: int
    failed: list[dict] = Field(
        description="Per-recipient failures as `{email, error}`."
    )


def _send_smtp(to_email: str, subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("SMTP_FROM", user)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(user, password)
        smtp.send_message(msg)


@app.post(
    "/admin/students/email",
    tags=["Admin - Students"],
    summary="Send a mass email to a filtered student cohort",
    description=(
        "Server resolves recipient addresses from the `filters` — the client "
        "**cannot** inject arbitrary recipient addresses. Uses the SMTP creds "
        "configured via `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, "
        "`SMTP_PASSWORD`, `SMTP_FROM` environment variables."
    ),
    response_model=MassEmailResponse,
    responses={503: {"description": "SMTP not configured on server"}},
)
def mass_email_students(
    payload: MassEmail,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    if "SMTP_HOST" not in os.environ or "SMTP_USER" not in os.environ:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "SMTP not configured on server"
        )

    students = _filtered_students_query(
        db, payload.filters.search, payload.filters.class_section
    ).all()
    recipients = [s.email_id for s in students]

    sent, failed = 0, []
    for email_addr in recipients:
        try:
            _send_smtp(email_addr, payload.subject, payload.body)
            sent += 1
        except Exception as exc:
            failed.append({"email": email_addr, "error": str(exc)})

    return {
        "recipients_matched": len(recipients),
        "sent": sent,
        "failed": failed,
    }


def _build_report_card_pdf(student, graded_rows, ungraded_subjects) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>REPORT CARD</b>", styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            f"<b>Name:</b> {student.name} &nbsp;&nbsp; "
            f"<b>School ID:</b> {student.school_id}",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"<b>Class:</b> {student.class_section.value}", styles["Normal"]
        )
    )
    story.append(Spacer(1, 0.3 * inch))

    table_data = [["Subject", "Obtained", "Max Marks"]]
    total_obtained = 0.0
    total_max = 0.0
    for subject, obtained, max_marks in graded_rows:
        table_data.append([subject, f"{obtained:g}", f"{max_marks:g}"])
        total_obtained += obtained
        total_max += max_marks
    for subject in ungraded_subjects:
        table_data.append([subject, "—", "—"])

    table = Table(table_data, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.whitesmoke, colors.white]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    if total_max > 0:
        percentage = total_obtained / total_max * 100
        story.append(
            Paragraph(
                f"<b>Total:</b> {total_obtained:g} / {total_max:g}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"<b>Percentage:</b> {percentage:.2f}%", styles["Normal"]
            )
        )
    else:
        story.append(
            Paragraph(
                "<i>No marks have been recorded yet.</i>", styles["Italic"]
            )
        )

    story.append(Spacer(1, 0.4 * inch))
    story.append(
        Paragraph(
            f"<font size=9 color='#888'>Generated: "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            f"</font>",
            styles["Normal"],
        )
    )

    doc.build(story)
    return buf.getvalue()


@app.get(
    "/student/report-card",
    tags=["Student"],
    summary="Download your report card as PDF",
    description=(
        "Returns a styled PDF with the student's name, school ID, class, "
        "per-subject marks (showing `—` for subjects not yet graded), total, "
        "and overall percentage (computed from graded subjects only)."
    ),
    response_class=StreamingResponse,
    responses={403: {"description": "Caller is not a student"}},
)
def download_report_card(
    student=Depends(require_student),
    db: Session = Depends(get_database),
):
    subjects = (
        db.query(models.StudentSubject)
        .filter(models.StudentSubject.student_id == student.id)
        .all()
    )
    marks_rows = (
        db.query(models.Marks)
        .filter(models.Marks.student_id == student.id)
        .all()
    )
    marks_by_subject = {m.subject: m for m in marks_rows}

    graded, ungraded = [], []
    for ss in subjects:
        m = marks_by_subject.get(ss.subject)
        if m is not None:
            graded.append((ss.subject, m.marks_obtained, m.max_marks))
        else:
            ungraded.append(ss.subject)

    pdf_bytes = _build_report_card_pdf(student, graded, ungraded)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"report-{student.school_id}-{stamp}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# You can keep your main function for local testing if you want,
# but FastAPI doesn't need it to run the server.

def main():
    print("This runs only if you execute 'python main.py' directly")

if __name__ == "__main__":
    main()