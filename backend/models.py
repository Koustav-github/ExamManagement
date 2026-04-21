import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Role(enum.Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class ClassLevel(enum.Enum):
    EIGHT = "8th Grade"
    NINE = "9th Grade"
    TEN = "10th Grade"
    ELEVEN_SC = "11th Grade Science"
    ELEVEN_COM = "11th Grade Commerce"
    ELEVEN_AR = "11th Grade Arts"
    TWELVE_SC = "12th Grade Science"
    TWELVE_COM = "12th Grade Commerce"
    TWELVE_AR = "12th Grade Arts"


class CoreSubject(enum.Enum):
    MATH = "Math"
    SCIENCE = "Science"
    SOCIAL_SCIENCE = "Social Science"
    ENGLISH = "English"
    HINDI = "Hindi"
    BENGALI = "Bengali"
    COMPUTER = "Computer"


class ScienceSubject(enum.Enum):
    PHYSICS = "Physics"
    CHEMISTRY = "Chemistry"
    MATH = "Math"
    BIOLOGY = "Biology"
    COMPUTER_SCIENCE = "Computer Science"
    ENGLISH = "English"


class CommerceSubject(enum.Enum):
    ACCOUNTANCY = "Accountancy"
    BUSINESS_STUDIES = "Business Studies"
    ECONOMICS = "Economics"
    MATH = "Math"
    ENGLISH = "English"
    COMPUTER_APPLICATIONS = "Computer Applications"


class ArtsSubject(enum.Enum):
    HISTORY = "History"
    GEOGRAPHY = "Geography"
    POLITICAL_SCIENCE = "Political Science"
    ECONOMICS = "Economics"
    ENGLISH = "English"
    SOCIOLOGY = "Sociology"


SUBJECTS_BY_CLASS: dict[ClassLevel, type[enum.Enum]] = {
    ClassLevel.EIGHT: CoreSubject,
    ClassLevel.NINE: CoreSubject,
    ClassLevel.TEN: CoreSubject,
    ClassLevel.ELEVEN_SC: ScienceSubject,
    ClassLevel.TWELVE_SC: ScienceSubject,
    ClassLevel.ELEVEN_COM: CommerceSubject,
    ClassLevel.TWELVE_COM: CommerceSubject,
    ClassLevel.ELEVEN_AR: ArtsSubject,
    ClassLevel.TWELVE_AR: ArtsSubject,
}


def valid_subject_for_class(class_level: ClassLevel, subject_name: str) -> bool:
    return subject_name in SUBJECTS_BY_CLASS[class_level].__members__


class Students(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    school_id = Column(String, unique=True, nullable=False, index=True)
    email_id = Column(String, unique=True, nullable=False, index=True)
    mobile_number = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    class_section = Column(Enum(ClassLevel), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.STUDENT)
    refresh_jti = Column(String, unique=True, nullable=True, index=True)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subjects = relationship(
        "StudentSubject", back_populates="student", cascade="all, delete-orphan"
    )
    marks = relationship(
        "Marks", back_populates="student", cascade="all, delete-orphan"
    )


class Teachers(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    teacher_id = Column(String, unique=True, nullable=False, index=True)
    email_id = Column(String, unique=True, nullable=False, index=True)
    mobile_number = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.TEACHER)
    refresh_jti = Column(String, unique=True, nullable=True, index=True)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subjects = relationship(
        "TeacherSubject", back_populates="teacher", cascade="all, delete-orphan"
    )
    marks_entered = relationship("Marks", back_populates="entered_by")


class Admins(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    admin_id = Column(String, unique=True, nullable=False, index=True)
    email_id = Column(String, unique=True, nullable=False, index=True)
    mobile_number = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    super_admin = Column(Boolean, nullable=False, default=False)
    role = Column(Enum(Role), nullable=False, default=Role.ADMIN)
    refresh_jti = Column(String, unique=True, nullable=True, index=True)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StudentSubject(Base):
    __tablename__ = "student_subjects"
    __table_args__ = (
        UniqueConstraint("student_id", "subject", name="uq_student_subject"),
    )

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject = Column(String, nullable=False)
    marks = Column(Float, nullable=False, server_default="0")

    student = relationship("Students", back_populates="subjects")


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "subject",
            "class_level",
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
    students = relationship(
        "TeacherSubjectStudent",
        back_populates="teacher_subject",
        cascade="all, delete-orphan",
    )


class TeacherSubjectStudent(Base):
    __tablename__ = "teacher_subject_students"
    __table_args__ = (
        UniqueConstraint(
            "teacher_subject_id",
            "student_id",
            name="uq_teacher_subject_student",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    teacher_subject_id = Column(
        Integer,
        ForeignKey("teacher_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marks = Column(Float, nullable=False, server_default="0")

    teacher_subject = relationship("TeacherSubject", back_populates="students")
    student = relationship("Students")


class Marks(Base):
    __tablename__ = "marks"
    __table_args__ = (
        UniqueConstraint("student_id", "subject", name="uq_marks_student_subject"),
    )

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject = Column(String, nullable=False)
    max_marks = Column(Float, nullable=False)
    marks_obtained = Column(Float, nullable=False)
    entered_by_teacher_id = Column(
        Integer,
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    student = relationship("Students", back_populates="marks")
    entered_by = relationship("Teachers", back_populates="marks_entered")
