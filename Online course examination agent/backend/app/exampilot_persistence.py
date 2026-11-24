"""Idempotent normalized PostgreSQL projection of existing ExamPilot JSON states."""

from datetime import datetime, timezone
from decimal import Decimal
import json

from sqlalchemy import select

from backend.app.models import (
    Question,
    AttemptQuestion,
    StudentAnswer,
    EvaluationResult,
)


def _json(obj):
    return json.loads(json.dumps(obj, default=str))


def _number(value, default="0"):
    try:
        return Decimal(
            str(value if value is not None else default)
        )
    except (ValueError, TypeError, ArithmeticError):
        return Decimal(default)


def _question_id(item):
    return str(
        item.get("question_id")
        or item.get("id")
        or ""
    )


def sync_state(db, state, attempt=None):
    """
    Synchronize existing JSON examination states with normalized
    PostgreSQL tables.

    Safe to execute repeatedly.
    """

    exam_id = str(state["_assignment_id"])

    questions = (
        state.get("questions")
        or state.get("validated_questions")
        or []
    )

    if not isinstance(questions, list):
        return

    existing = {
        q.external_id: q
        for q in db.scalars(
            select(Question).where(
                Question.exam_id == exam_id
            )
        ).all()
    }

    by_external = {}

    # --------------------------------------------------
    # Synchronize questions
    # --------------------------------------------------

    for index, raw in enumerate(questions):

        if not isinstance(raw, dict):
            continue

        ext = _question_id(raw)

        if not ext:
            continue

        q = existing.get(ext)

        if q is None:

            q = Question(
                exam_id=exam_id,
                external_id=ext,
                position=index,
                question_type=str(
                    raw.get("question_type")
                    or raw.get("type")
                    or ""
                )[:60] or None,
                question_data=_json(raw),
                max_marks=_number(
                    raw.get(
                        "marks",
                        raw.get("max_marks", 1)
                    ),
                    "1",
                ),
            )

            db.add(q)
            db.flush()

            existing[ext] = q

        by_external[ext] = q

    if attempt is None:
        return

    # --------------------------------------------------
    # Synchronize attempt questions
    # --------------------------------------------------

    aqs = {
        aq.question_id: aq
        for aq in db.scalars(
            select(AttemptQuestion).where(
                AttemptQuestion.attempt_id == attempt.id
            )
        ).all()
    }

    for index, raw in enumerate(questions):

        if not isinstance(raw, dict):
            continue

        q = by_external.get(_question_id(raw))

        if q is None:
            continue

        if q.id not in aqs:

            aq = AttemptQuestion(
                attempt_id=attempt.id,
                question_id=q.id,
                position=index,
                question_snapshot=_json(raw),
            )

            db.add(aq)
            db.flush()

            aqs[q.id] = aq

    # --------------------------------------------------
    # Synchronize student answers
    # --------------------------------------------------

    answers = state.get("answers") or []

    if isinstance(answers, dict):

        answers = [
            dict(v, question_id=k)
            if isinstance(v, dict)
            else {
                "question_id": k,
                "answer": v,
            }
            for k, v in answers.items()
        ]

    graded = {
        str(r.get("question_id")): r
        for r in (
            state.get("evaluation_results") or []
        )
        if isinstance(r, dict)
    }

    existing_answers = {
        a.attempt_question_id: a
        for a in db.scalars(
            select(StudentAnswer)
            .join(
                AttemptQuestion,
                StudentAnswer.attempt_question_id
                == AttemptQuestion.id,
            )
            .where(
                AttemptQuestion.attempt_id == attempt.id
            )
        ).all()
    }

    for raw in answers:

        if not isinstance(raw, dict):
            continue

        q = by_external.get(_question_id(raw))

        aq = aqs.get(q.id) if q else None

        if aq is None:
            continue

        record = existing_answers.get(aq.id)

        if record is None:

            record = StudentAnswer(
                attempt_question_id=aq.id,
                answer_text="",
            )

            db.add(record)
            existing_answers[aq.id] = record

        answer_value = raw.get(
            "answer",
            raw.get(
                "answer_text",
                raw.get("submitted_answer", ""),
            ),
        )

        record.answer_text = str(
            answer_value
            if answer_value is not None
            else ""
        )

        grade = graded.get(_question_id(raw))

        if grade:

            record.is_correct = (
                grade.get("correct")
                if isinstance(grade.get("correct"), bool)
                else None
            )

            record.marks_awarded = _number(
                grade.get("marks_awarded")
            )

            record.automatic_feedback = _json({
                "feedback": grade.get("feedback")
            })

            record.graded_at = datetime.now(timezone.utc)

    # --------------------------------------------------
    # Synchronize final evaluation result
    # --------------------------------------------------

    result = state.get("final_result")

    if isinstance(result, dict) and result:

        rec = db.scalar(
            select(EvaluationResult).where(
                EvaluationResult.attempt_id == attempt.id
            )
        )

        if rec is None:

            rec = EvaluationResult(
                attempt_id=attempt.id
            )

            db.add(rec)

        rec.marks_obtained = _number(
            result.get(
                "marks_awarded",
                result.get("marks_obtained", 0),
            )
        )

        rec.total_marks = _number(
            result.get("total_marks", 0)
        )

        rec.percentage = max(
            Decimal("0"),
            min(
                Decimal("100"),
                _number(result.get("percentage", 0)),
            ),
        )

        rec.status = "evaluated"
        rec.final_result = _json(result)

        rec.evaluation_details = _json(
            state.get("evaluation_results") or []
        )

        rec.evaluated_at = datetime.now(timezone.utc)

        if attempt.evaluated_at is None:
            attempt.evaluated_at = rec.evaluated_at