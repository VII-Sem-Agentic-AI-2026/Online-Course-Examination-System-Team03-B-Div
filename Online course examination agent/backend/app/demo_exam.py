
from __future__ import annotations

from typing import Any


DEMO_SUBJECT = "DBMS - Development Test"
DEMO_TOPIC = "Reusable Proctoring Test"

# This is deliberately a fixed, non-AI question bank.
DEMO_QUESTIONS: list[dict[str, Any]] = [
    {
        "question_id": "demo_q1",
        "question_type": "normal_mcq",
        "question": "Which SQL command retrieves data?",
        "options": {
            "A": "SELECT",
            "B": "DROP",
            "C": "DELETE",
            "D": "ALTER",
        },
        "correct_answer": "A",
        "marks": 2,
        "total_marks": 2,
    },
    {
        "question_id": "demo_q2",
        "question_type": "normal_mcq",
        "question": "What does DBMS stand for?",
        "options": {
            "A": "Data Backup Management Software",
            "B": "Database Management System",
            "C": "Digital Business Management Service",
            "D": "Database Memory Storage",
        },
        "correct_answer": "B",
        "marks": 2,
        "total_marks": 2,
    },
    {
        "question_id": "demo_q3",
        "question_type": "normal_mcq",
        "question": "Which command removes an SQL table?",
        "options": {
            "A": "REMOVE",
            "B": "CLEAR",
            "C": "DROP",
            "D": "SELECT",
        },
        "correct_answer": "C",
        "marks": 2,
        "total_marks": 2,
    },
    {
        "question_id": "demo_q4",
        "question_type": "normal_mcq",
        "question": "Which key uniquely identifies a row?",
        "options": {
            "A": "Foreign key",
            "B": "Composite index",
            "C": "Candidate column",
            "D": "Primary key",
        },
        "correct_answer": "D",
        "marks": 2,
        "total_marks": 2,
    },
    {
        "question_id": "demo_q5",
        "question_type": "normal_mcq",
        "question": "Which SQL clause filters rows?",
        "options": {
            "A": "WHERE",
            "B": "ORDER BY",
            "C": "GROUP BY",
            "D": "JOIN",
        },
        "correct_answer": "A",
        "marks": 2,
        "total_marks": 2,
    },
]


def grade_demo_attempt(
    state: dict[str, Any],
) -> dict[str, Any]:
    """Grade a demo attempt using fixed answer keys.

    This function does not call Gemini or any AI model.
    """
    session = state.get("exam_session") or {}

    # Prefer the actual saved session answers.
    stored_answers = session.get("answers") or {}

    answer_map: dict[str, str] = {}

    if isinstance(stored_answers, dict):
        for question_id, entry in stored_answers.items():
            value = (
                entry.get("answer", "")
                if isinstance(entry, dict)
                else entry
            )
            answer_map[str(question_id)] = str(value).strip()

    elif isinstance(stored_answers, list):
        for entry in stored_answers:
            if not isinstance(entry, dict):
                continue

            question_id = entry.get("question_id")
            if question_id:
                answer_map[str(question_id)] = str(
                    entry.get("answer", "")
                ).strip()

    # Support ExamPilot's flattened answers state too.
    for entry in state.get("answers") or []:
        if isinstance(entry, dict) and entry.get("question_id"):
            answer_map[str(entry["question_id"])] = str(
                entry.get("answer", "")
            ).strip()

    results = []

    for question in DEMO_QUESTIONS:
        question_id = question["question_id"]
        selected = answer_map.get(question_id, "")
        expected = question["correct_answer"]

        correct = selected.upper() == expected

        results.append({
            "question_id": question_id,
            "question": question["question"],
            "student_answer": selected,
            "correct_answer": expected,
            "is_correct": correct,
            "marks_awarded": 2 if correct else 0,
            "total_marks": 2,
            "feedback": (
                "Correct answer."
                if correct
                else f"Correct option: {expected}"
            ),
        })

    obtained = sum(r["marks_awarded"] for r in results)
    total = sum(r["total_marks"] for r in results)

    return {
        "current_stage": "completed",
        "evaluation_results": results,
        "final_result": {
            "status": "completed",
            "results": results,
            "total_marks": total,
            "marks_awarded": obtained,
            "percentage": round(
                obtained / total * 100, 2
            ) if total else 0,
        },
    }
