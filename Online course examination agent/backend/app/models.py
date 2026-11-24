"""PostgreSQL models for persistent ExamPilot records."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    roll_number: Mapped[int | None] = mapped_column(Integer)
    usn: Mapped[str | None] = mapped_column(String(50))
    division: Mapped[str | None] = mapped_column(String(30))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'teacher')",
            name="ck_user_role",
        ),
    )


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)

    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    division: Mapped[str] = mapped_column(String(30), nullable=False)

    subject: Mapped[str | None] = mapped_column(String(150))
    topic: Mapped[str | None] = mapped_column(String(200))
    difficulty: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(250))

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    scheduled_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    scheduled_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )

    generation_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "duration_minutes > 0",
            name="ck_exam_duration_positive",
        ),
        Index("ix_exams_teacher_created", "teacher_id", "created_at"),
        Index("ix_exams_division", "division"),
    )


class ExamAssignment(Base):
    __tablename__ = "exam_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    exam_id: Mapped[str] = mapped_column(
        ForeignKey("exams.id"),
        nullable=False,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "student_id",
            name="uq_exam_assignment_student",
        ),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    exam_id: Mapped[str] = mapped_column(
        ForeignKey("exams.id"),
        nullable=False,
    )

    external_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    question_type: Mapped[str | None] = mapped_column(String(60))

    question_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    max_marks: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("1.00"),
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "external_id",
            name="uq_exam_question_external",
        ),
        UniqueConstraint(
            "exam_id",
            "position",
            name="uq_exam_question_position",
        ),
    )


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    exam_id: Mapped[str] = mapped_column(
        ForeignKey("exams.id"),
        nullable=False,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="in_progress",
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    session_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "student_id",
            name="uq_exam_attempt_student",
        ),
        Index("ix_attempts_exam_status", "exam_id", "status"),
    )


class AttemptQuestion(Base):
    __tablename__ = "attempt_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id"),
        nullable=False,
    )

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id"),
        nullable=False,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    question_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "question_id",
            name="uq_attempt_question",
        ),
        UniqueConstraint(
            "attempt_id",
            "position",
            name="uq_attempt_position",
        ),
    )


class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    attempt_question_id: Mapped[int] = mapped_column(
        ForeignKey("attempt_questions.id"),
        nullable=False,
        unique=True,
    )

    answer_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    is_correct: Mapped[bool | None] = mapped_column(Boolean)

    marks_awarded: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )

    automatic_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    graded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id"),
        nullable=False,
        unique=True,
    )

    marks_obtained: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    total_marks: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="evaluated",
    )

    final_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    evaluation_details: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        CheckConstraint(
            "marks_obtained >= 0",
            name="ck_result_marks_nonnegative",
        ),
        CheckConstraint(
            "total_marks >= 0",
            name="ck_result_total_nonnegative",
        ),
        CheckConstraint(
            "percentage BETWEEN 0 AND 100",
            name="ck_result_percentage_range",
        ),
    )


class TeacherFeedback(Base):
    __tablename__ = "teacher_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id"),
        nullable=False,
    )

    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("student_answers.id")
    )

    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        Index("ix_teacher_feedback_attempt", "attempt_id"),
    )


class ProctoringEvent(Base):
    __tablename__ = "proctoring_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_proctoring_attempt_time",
            "attempt_id",
            "occurred_at",
        ),
    )