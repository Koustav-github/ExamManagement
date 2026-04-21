from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import get_database
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr, Field
import models
import os
from dotenv import load_dotenv

# 1. Create the app instance (the CLI looks for this variable name)
app = FastAPI(title="Academic Report backend")
load_dotenv()

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
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)
    role: models.Role


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

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
    

@app.post("/user/signin", response_model=LoginResponse)
def sync_user(
    user_data: UserSync,
    response: Response,
    db: Session = Depends(get_database),
):
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

@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
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


class StudentCreate(BaseModel):
    name: str
    school_id: str
    email: EmailStr
    mobile_number: str
    password: str = Field(min_length=1, max_length=72)
    class_section: models.ClassLevel


class TeacherCreate(BaseModel):
    name: str
    teacher_id: str
    email: EmailStr
    mobile_number: str
    password: str = Field(min_length=1, max_length=72)


class AdminCreate(BaseModel):
    name: str
    admin_id: str
    email: EmailStr
    mobile_number: str
    password: str = Field(min_length=1, max_length=72)
    super_admin: bool = False


@app.post("/admin/students", status_code=status.HTTP_201_CREATED)
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
    db.add(student)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "school_id or email already exists"
        )
    db.refresh(student)
    return {
        "id": student.id,
        "school_id": student.school_id,
        "email": student.email_id,
        "role": student.role.value,
    }


@app.post("/admin/teachers", status_code=status.HTTP_201_CREATED)
def create_teacher(
    payload: TeacherCreate,
    _admin=Depends(require_admin),
    db: Session = Depends(get_database),
):
    teacher = models.Teachers(
        name=payload.name,
        teacher_id=payload.teacher_id,
        email_id=payload.email,
        mobile_number=payload.mobile_number,
        password_hash=hash_password(payload.password),
    )
    db.add(teacher)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "teacher_id or email already exists"
        )
    db.refresh(teacher)
    return {
        "id": teacher.id,
        "teacher_id": teacher.teacher_id,
        "email": teacher.email_id,
        "role": teacher.role.value,
    }


@app.post("/admin/admins", status_code=status.HTTP_201_CREATED)
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


# You can keep your main function for local testing if you want,
# but FastAPI doesn't need it to run the server.

def main():
    print("This runs only if you execute 'python main.py' directly")

if __name__ == "__main__":
    main()