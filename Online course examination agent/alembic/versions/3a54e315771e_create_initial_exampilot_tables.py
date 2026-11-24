"""create initial exampilot tables

Revision ID: 3a54e315771e
Revises:
Create Date: 2026-11-15 20:26:53.504619
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '3a54e315771e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('roll_number', sa.Integer(), nullable=True),
        sa.Column('usn', sa.String(length=50), nullable=True),
        sa.Column('division', sa.String(length=30), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('student', 'teacher')",
            name='ck_user_role'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    op.create_table(
        'exams',
        sa.Column('id', sa.String(length=128), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('division', sa.String(length=30), nullable=False),
        sa.Column('subject', sa.String(length=150), nullable=True),
        sa.Column('topic', sa.String(length=200), nullable=True),
        sa.Column('difficulty', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=250), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column(
            'scheduled_start_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column(
            'scheduled_end_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column(
            'generation_state',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.CheckConstraint(
            'duration_minutes > 0',
            name='ck_exam_duration_positive'
        ),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        'ix_exams_division',
        'exams',
        ['division'],
        unique=False
    )

    op.create_index(
        'ix_exams_teacher_created',
        'exams',
        ['teacher_id', 'created_at'],
        unique=False
    )

    op.create_table(
        'exam_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exam_id', sa.String(length=128), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column(
            'assigned_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'exam_id',
            'student_id',
            name='uq_exam_assignment_student'
        )
    )

    op.create_table(
        'exam_attempts',
        sa.Column('id', sa.String(length=128), nullable=False),
        sa.Column('exam_id', sa.String(length=128), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'session_state',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'exam_id',
            'student_id',
            name='uq_exam_attempt_student'
        )
    )

    op.create_index(
        'ix_attempts_exam_status',
        'exam_attempts',
        ['exam_id', 'status'],
        unique=False
    )

    op.create_table(
        'questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exam_id', sa.String(length=128), nullable=False),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('question_type', sa.String(length=60), nullable=True),
        sa.Column(
            'question_data',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False
        ),
        sa.Column(
            'max_marks',
            sa.Numeric(precision=10, scale=2),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'exam_id',
            'external_id',
            name='uq_exam_question_external'
        ),
        sa.UniqueConstraint(
            'exam_id',
            'position',
            name='uq_exam_question_position'
        )
    )

    op.create_table(
        'attempt_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.String(length=128), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column(
            'question_snapshot',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['attempt_id'], ['exam_attempts.id']),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'attempt_id',
            'position',
            name='uq_attempt_position'
        ),
        sa.UniqueConstraint(
            'attempt_id',
            'question_id',
            name='uq_attempt_question'
        )
    )

    op.create_table(
        'evaluation_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.String(length=128), nullable=False),
        sa.Column('marks_obtained', sa.Numeric(10, 2), nullable=False),
        sa.Column('total_marks', sa.Numeric(10, 2), nullable=False),
        sa.Column('percentage', sa.Numeric(5, 2), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column(
            'final_result',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.Column(
            'evaluation_details',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.Column(
            'evaluated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column(
            'published_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.CheckConstraint(
            'marks_obtained >= 0',
            name='ck_result_marks_nonnegative'
        ),
        sa.CheckConstraint(
            'percentage BETWEEN 0 AND 100',
            name='ck_result_percentage_range'
        ),
        sa.CheckConstraint(
            'total_marks >= 0',
            name='ck_result_total_nonnegative'
        ),
        sa.ForeignKeyConstraint(['attempt_id'], ['exam_attempts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_id')
    )

    op.create_table(
        'proctoring_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column(
            'details',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.Column(
            'occurred_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['attempt_id'], ['exam_attempts.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        'ix_proctoring_attempt_time',
        'proctoring_events',
        ['attempt_id', 'occurred_at'],
        unique=False
    )

    op.create_table(
        'student_answers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_question_id', sa.Integer(), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=False),
        sa.Column(
            'saved_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('marks_awarded', sa.Numeric(10, 2), nullable=True),
        sa.Column(
            'automatic_feedback',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True
        ),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['attempt_question_id'],
            ['attempt_questions.id']
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_question_id')
    )

    op.create_table(
        'teacher_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.String(length=128), nullable=False),
        sa.Column('answer_id', sa.Integer(), nullable=True),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['answer_id'], ['student_answers.id']),
        sa.ForeignKeyConstraint(['attempt_id'], ['exam_attempts.id']),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        'ix_teacher_feedback_attempt',
        'teacher_feedback',
        ['attempt_id'],
        unique=False
    )


def downgrade() -> None:

    op.drop_index(
        'ix_teacher_feedback_attempt',
        table_name='teacher_feedback'
    )
    op.drop_table('teacher_feedback')

    op.drop_table('student_answers')

    op.drop_index(
        'ix_proctoring_attempt_time',
        table_name='proctoring_events'
    )
    op.drop_table('proctoring_events')

    op.drop_table('evaluation_results')
    op.drop_table('attempt_questions')
    op.drop_table('questions')

    op.drop_index(
        'ix_attempts_exam_status',
        table_name='exam_attempts'
    )
    op.drop_table('exam_attempts')

    op.drop_table('exam_assignments')

    op.drop_index(
        'ix_exams_teacher_created',
        table_name='exams'
    )
    op.drop_index(
        'ix_exams_division',
        table_name='exams'
    )
    op.drop_table('exams')

    op.drop_table('users')