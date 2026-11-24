from backend.app.graph.exam_graph import evaluation_node


def make_state(answer="A", status="submitted"):
    answers = []
    if answer is not None:
        answers.append({"question_id": "q1", "answer": answer})

    return {
        "exam_session": {
            "session_id": "session-test-1",
            "student_id": "student-test-1",
            "status": status,
        },
        "questions": [
            {
                "question_id": "q1",
                "question_type": "normal_mcq",
                "question": "Which SQL command retrieves data?",
                "options": {
                    "A": "SELECT",
                    "B": "DELETE",
                    "C": "DROP",
                    "D": "UPDATE",
                },
                "correct_answer": "A",
                "marks": 2,
            }
        ],
        "answers": answers,
        "trace": [],
        "errors": [],
    }


def test_correct_mcq_label():
    result = evaluation_node(make_state("A"))
    assert result["final_result"]["marks_awarded"] == 2
    assert result["final_result"]["percentage"] == 100
    print("PASS: Correct option label")


def test_correct_mcq_text():
    result = evaluation_node(make_state("SELECT"))
    assert result["final_result"]["marks_awarded"] == 2
    print("PASS: Correct option text")


def test_incorrect_mcq():
    result = evaluation_node(make_state("B"))
    assert result["final_result"]["marks_awarded"] == 0
    assert result["final_result"]["percentage"] == 0
    print("PASS: Incorrect answer")


def test_unanswered_question():
    result = evaluation_node(make_state(None))
    assert result["final_result"]["marks_awarded"] == 0
    assert result["final_result"]["answered_questions"] == 0
    print("PASS: Unanswered question")


def test_sql_coding_answer():
    state = make_state()
    state["questions"] = [
        {
            "question_id": "q2",
            "question_type": "coding",
            "question": "Retrieve all students.",
            "expected_answer": "SELECT * FROM students",
            "schema_sql": """
                CREATE TABLE students (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                );
            """,
            "test_data_sql": """
                INSERT INTO students (id, name) VALUES
                (1, 'Asha'),
                (2, 'Ravi');
            """,
            "marks": 5,
        }
    ]
    state["answers"] = [
        {
            "question_id": "q2",
            "answer": "SELECT * FROM students",
        }
    ]

    result = evaluation_node(state)
    final_result = result["final_result"]

    assert final_result["marks_awarded"] == 5, final_result
    assert final_result["total_marks"] == 5, final_result

    question_result = next(
        item for item in final_result["results"]
        if item.get("question_id") == "q2"
    )
    assert question_result.get("marks_awarded") == 5, question_result

    print("PASS: SQL coding answer receives full marks")


def test_unsubmitted_exam_rejected():
    result = evaluation_node(make_state("A", status="in_progress"))
    assert result["current_stage"] == "error"
    print("PASS: Unsubmitted exam rejected")


if __name__ == "__main__":
    test_correct_mcq_label()
    test_correct_mcq_text()
    test_incorrect_mcq()
    test_unanswered_question()
    test_sql_coding_answer()
    test_unsubmitted_exam_rejected()
    print("\nAll evaluation tests passed.")