from backend.app.graph.exam_graph import (
    create_exam_state,
    exam_graph,
)
from backend.app.schemas.exam_request import ExamRequest
from backend.app.schemas.student import Student


# ============================================================
# TEST CONFIGURATION
# ============================================================

TEACHER_ID = 2

DOCUMENT_IDS = [
    "29e2106d-efbc-4ed5-bb55-a52417d622d7"
]

EXPECTED_QUESTIONS = 3


# ============================================================
# CREATE TEST STUDENT
# ============================================================

student = Student(
    roll_number=2,
    usn="01FE23BCI002",
    name="Full Graph Test Student",
    division="A",
)


# ============================================================
# CREATE EXAM REQUEST
# ============================================================

exam_request = ExamRequest(
    student=student,
    subject="OOP",
    topic="Classes and Objects",
    difficulty="L1",
    number_of_questions=EXPECTED_QUESTIONS,
    question_mix={
        "normal_mcq": 3,
        "scenario_mcq": 0,
        "coding": 0,
    },
    document_ids=DOCUMENT_IDS,
)


# ============================================================
# INITIALIZE GRAPH STATE
# ============================================================

state = create_exam_state(exam_request)

state["requirements"]["teacher_id"] = TEACHER_ID
state["requirements"]["document_ids"] = DOCUMENT_IDS
state["requirements"]["notes_only"] = True


# ============================================================
# EXECUTE COMPLETE LANGGRAPH
# ============================================================

print("\n" + "=" * 60)
print("FULL LANGGRAPH INTEGRATION TEST")
print("=" * 60)

print("\nStarting complete exam generation workflow...")

try:
    final_state = exam_graph.invoke(
        state,
        config={"recursion_limit": 30},
    )

except Exception as exc:
    raise RuntimeError(
        f"Full LangGraph execution failed: {exc}"
    ) from exc


# ============================================================
# VERIFY GRAPH EXECUTION
# ============================================================

print("\nSTEP 1: GRAPH EXECUTION")
print("=" * 60)

print("Final stage:", final_state.get("current_stage"))
print("Errors:", final_state.get("errors", []))

if final_state.get("errors"):
    raise RuntimeError(
        f"Graph reported errors: {final_state['errors']}"
    )

assert final_state.get("current_stage") == "completed", (
    "Graph did not reach the completed stage."
)

print("PASS: Graph completed successfully.")


# ============================================================
# VERIFY NOTES RETRIEVAL
# ============================================================

print("\nSTEP 2: NOTES RETRIEVAL")
print("=" * 60)

retrieved_chunks = final_state.get("retrieved_chunks", [])

assert retrieved_chunks, (
    "No professor notes were retrieved."
)

assert final_state.get("retrieved_context"), (
    "Retrieved context is empty."
)

print("PASS: Professor notes retrieved.")
print("Retrieved chunks:", len(retrieved_chunks))


# ============================================================
# VERIFY QUESTION GENERATION
# ============================================================

print("\nSTEP 3: QUESTION GENERATION")
print("=" * 60)

questions = final_state.get("questions", [])

assert len(questions) == EXPECTED_QUESTIONS, (
    f"Expected {EXPECTED_QUESTIONS} questions, "
    f"received {len(questions)}."
)

print("PASS: Correct number of questions generated.")


# ============================================================
# VERIFY VALIDATION
# ============================================================

print("\nSTEP 4: QUESTION VALIDATION")
print("=" * 60)

assert final_state.get("validation_status") == "passed", (
    "Question validation did not pass."
)

valid_chunk_ids = {
    chunk["chunk_id"]
    for chunk in retrieved_chunks
}

for index, question in enumerate(questions, start=1):

    assert question.get("source") == "professor_notes", (
        f"Question {index} has an invalid source."
    )

    assert question.get("source_chunk_ids"), (
        f"Question {index} has no source chunk IDs."
    )

    assert question.get("supporting_quote"), (
        f"Question {index} has no supporting quote."
    )

    assert set(question["source_chunk_ids"]).issubset(
        valid_chunk_ids
    ), (
        f"Question {index} references invalid chunks."
    )

print("PASS: All questions validated against professor notes.")


# ============================================================
# VERIFY EXAM SESSION
# ============================================================

print("\nSTEP 5: EXAM SESSION")
print("=" * 60)

exam_session = final_state.get("exam_session", {})

assert exam_session, (
    "Exam session was not created."
)

assert exam_session.get("student_id") == student.usn, (
    "Student ID mismatch."
)

assert exam_session.get("session_id"), (
    "Session ID is missing."
)

print("PASS: Exam session created.")
print("Session ID:", exam_session.get("session_id"))


# ============================================================
# VERIFY STUDENT QUESTIONS
# ============================================================

print("\nSTEP 6: STUDENT QUESTIONS")
print("=" * 60)

student_questions = final_state.get("student_questions", [])

assert len(student_questions) == EXPECTED_QUESTIONS, (
    "Incorrect number of student-facing questions."
)

print("PASS: Student questions prepared.")


# ============================================================
# VERIFY NO OPENCLAW EXECUTION
# ============================================================

print("\nSTEP 7: OPENCLAW BYPASS")
print("=" * 60)

trace = final_state.get("trace", [])

for entry in trace:

    if isinstance(entry, dict):

        agent = str(entry.get("agent", "")).lower()

        assert "openclaw" not in agent, (
            "OpenClaw was unexpectedly executed."
        )

print("PASS: No OpenClaw execution recorded.")


# ============================================================
# FINAL SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("FULL LANGGRAPH INTEGRATION TEST PASSED")
print("=" * 60)

print("Professor notes retrieval : PASS")
print("Question generation       : PASS")
print("Source verification       : PASS")
print("Question validation       : PASS")
print("Exam session creation     : PASS")
print("Student question delivery : PASS")
print("OpenClaw bypass           : PASS")

print("=" * 60)