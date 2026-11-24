from backend.app.graph.exam_graph import (
    create_exam_state,
    exam_session_node,
    question_generation_agent_node,
    validation_agent_node,
)
from backend.app.graph.mcp_node import mcp_node
from backend.app.schemas.exam_request import ExamRequest
from backend.app.schemas.student import Student


# ============================================================
# 1. TEST CONFIGURATION
# ============================================================

TEACHER_ID = 2

DOCUMENT_IDS = [
    "29e2106d-efbc-4ed5-bb55-a52417d622d7"
]

EXPECTED_QUESTIONS = 3

student = Student(
    roll_number=2,
    usn="01FE23BCI002",
    name="Retrieval Test Student",
    division="A",
)

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

state = create_exam_state(exam_request)

state["requirements"]["teacher_id"] = TEACHER_ID
state["requirements"]["document_ids"] = DOCUMENT_IDS
state["requirements"]["notes_only"] = True


# ============================================================
# HELPER: DISPLAY QUESTION OPTIONS
# ============================================================

def display_options(options):
    """
    Supports options stored as:
    1. Dictionary
    2. List of dictionaries
    3. List of strings
    """

    if isinstance(options, dict):

        for key, value in options.items():

            if isinstance(value, dict):
                label = value.get("label", value.get("text", ""))
                print(f"{key}. {label}")

            else:
                print(f"{key}. {value}")

    elif isinstance(options, list):

        for index, option in enumerate(options):

            if isinstance(option, dict):

                label = (
                    option.get("label")
                    or option.get("text")
                    or option.get("value")
                    or str(option)
                )

                option_id = option.get(
                    "value",
                    chr(65 + index)
                )

                print(f"{option_id}. {label}")

            else:
                print(f"{chr(65 + index)}. {option}")

    else:
        print("WARNING: Options are missing or in an unsupported format.")
        print("Raw options:", options)


# ============================================================
# 2. PROFESSOR NOTES RETRIEVAL
# ============================================================

print("\nSTEP 1: PROFESSOR NOTES RETRIEVAL")
print("=" * 60)

retrieval_result = mcp_node(state)
state.update(retrieval_result)

if state.get("errors"):
    raise RuntimeError(
        f"Notes retrieval failed: {state['errors']}"
    )

retrieved_chunks = state.get("retrieved_chunks", [])

if not retrieved_chunks:
    raise RuntimeError(
        "No professor notes chunks retrieved."
    )

print("PASS: Professor notes retrieved.")
print("Retrieved chunks:", len(retrieved_chunks))
print("Source documents:", DOCUMENT_IDS)

print(
    "Retrieved chunk IDs:",
    [chunk["chunk_id"] for chunk in retrieved_chunks]
)


# ============================================================
# 3. NOTES-ONLY QUESTION GENERATION
# ============================================================

print("\nSTEP 2: QUESTION GENERATION")
print("=" * 60)

generation_result = question_generation_agent_node(state)
state.update(generation_result)

questions = state.get("questions", [])

if not questions:
    raise RuntimeError(
        "Gemini did not generate any questions."
    )

print("PASS: Questions generated.")
print("Total questions:", len(questions))


if len(questions) != EXPECTED_QUESTIONS:
    raise RuntimeError(
        f"Expected {EXPECTED_QUESTIONS} questions, "
        f"but Gemini generated {len(questions)}."
    )


# ============================================================
# 4. DISPLAY COMPLETE MCQs
# ============================================================

print("\nGENERATED EXAM QUESTIONS")
print("=" * 60)

for index, question in enumerate(questions, start=1):

    print(f"\nQUESTION {index}")
    print("-" * 60)

    print("Question:")
    print(question.get("question", "Missing question text"))

    print("\nOptions:")

    options = question.get("options")

    display_options(options)

    print("\nCorrect Answer:")
    print(
        question.get("correct_answer")
        or question.get("correct_answer_text")
        or question.get("correctValues")
        or "Not available"
    )

    print("\nExplanation:")
    print(
        question.get("explanation")
        or question.get("answer_explanation")
        or "Not available"
    )

    print("\nSource:", question.get("source"))

    print("Source Chunks:", question.get("source_chunk_ids"))

    print("Supporting Quote:", question.get("supporting_quote"))


# ============================================================
# 5. BASIC MCQ STRUCTURE CHECK
# ============================================================

print("\nSTEP 3: MCQ STRUCTURE CHECK")
print("=" * 60)

for index, question in enumerate(questions, start=1):

    options = question.get("options")

    if isinstance(options, dict):
        option_count = len(options)

    elif isinstance(options, list):
        option_count = len(options)

    else:
        raise RuntimeError(
            f"Question {index} has missing or invalid options."
        )

    if option_count != 4:
        raise RuntimeError(
            f"Question {index} has {option_count} options. "
            "Every normal MCQ must have exactly four options."
        )

    print(f"Question {index}: PASS - Four options present.")


# ============================================================
# 6. QUESTION VALIDATION
# ============================================================

print("\nSTEP 4: QUESTION VALIDATION")
print("=" * 60)

validation_result = validation_agent_node(state)
state.update(validation_result)

validation_status = state.get("validation_status")

print("Validation status:", validation_status)

for result in state.get("validation_results", []):
    print(result)

if validation_status != "passed":
    raise RuntimeError(
        "Question validation failed. "
        f"Results: {state.get('validation_results')}"
    )

print("PASS: All questions passed validation.")


# ============================================================
# 7. VERIFY NOTES-ONLY SOURCE
# ============================================================

print("\nSTEP 5: SOURCE VERIFICATION")
print("=" * 60)

valid_chunk_ids = {
    chunk["chunk_id"]
    for chunk in retrieved_chunks
}

for index, question in enumerate(state["questions"], start=1):

    assert question.get("source") == "professor_notes", (
        f"Question {index} was not generated from professor notes."
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
        f"Question {index} references chunks that were not retrieved."
    )

print("PASS: All questions reference retrieved professor notes.")


# ============================================================
# 8. EXAM SESSION CREATION
# ============================================================

print("\nSTEP 6: EXAM SESSION CREATION")
print("=" * 60)

session_state = {
    **state,
    "student": student.model_dump(),
    "exam_session": {},
    "errors": [],
    "trace": [],
}

session_result = exam_session_node(session_state)

exam_session = session_result.get("exam_session", {})

if not exam_session:
    raise RuntimeError(
        "Exam session creation failed: "
        f"{session_result.get('errors', [])}"
    )

assert exam_session.get("student_id") == student.usn

print("PASS: Exam session created.")
print("Student ID:", exam_session.get("student_id"))
print("Session ID:", exam_session.get("session_id"))


# ============================================================
# FINAL RESULT
# ============================================================

print("\n" + "=" * 60)
print("NOTES-ONLY PIPELINE TEST COMPLETED")
print("=" * 60)

print("Notes retrieval        : PASS")
print("Gemini generation      : PASS")
print("MCQ structure check    : PASS")
print("Question validation    : PASS")
print("Notes-only verification: PASS")
print("Exam session creation  : PASS")

print("=" * 60)