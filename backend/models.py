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
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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

    student = relationship("Students", back_populates="subjects")


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
