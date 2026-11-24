from backend.app.agents.evaluation_agent.sql_grader import grade_sql_answer


SCHEMA = """
CREATE TABLE Students (
    id INTEGER,
    name TEXT,
    score INTEGER
);
"""

TEST_DATA = """
INSERT INTO Students VALUES (1, 'Asha', 90);
INSERT INTO Students VALUES (2, 'Ravi', 75);
INSERT INTO Students VALUES (3, 'Mina', 85);
"""


def test_correct_sql():
    result = grade_sql_answer(
        student_sql="SELECT name FROM Students WHERE id = 1",
        expected_sql="SELECT name FROM Students WHERE id=1",
        schema_sql=SCHEMA,
        test_data_sql=TEST_DATA,
        marks=2,
    )
    assert result["status"] == "correct", result
    assert result["marks_awarded"] == 2
    print("PASS: Equivalent SQL receives full marks")


def test_incorrect_sql():
    result = grade_sql_answer(
        student_sql="SELECT name FROM Students WHERE id = 2",
        expected_sql="SELECT name FROM Students WHERE id = 1",
        schema_sql=SCHEMA,
        test_data_sql=TEST_DATA,
        marks=2,
    )
    assert result["status"] == "incorrect", result
    assert result["marks_awarded"] == 0
    print("PASS: Incorrect SQL receives zero marks")


def test_invalid_sql():
    result = grade_sql_answer(
        student_sql="SELECT invalid_column FROM Students",
        expected_sql="SELECT name FROM Students WHERE id = 1",
        schema_sql=SCHEMA,
        test_data_sql=TEST_DATA,
        marks=2,
    )
    assert result["status"] == "incorrect", result
    assert result["marks_awarded"] == 0
    print("PASS: Invalid SQL receives zero marks")


def test_write_query_rejected():
    result = grade_sql_answer(
        student_sql="DELETE FROM Students",
        expected_sql="SELECT name FROM Students WHERE id = 1",
        schema_sql=SCHEMA,
        test_data_sql=TEST_DATA,
        marks=2,
    )
    assert result["status"] == "rejected", result
    assert result["marks_awarded"] == 0
    print("PASS: Write query is rejected")


def test_empty_answer():
    result = grade_sql_answer(
        student_sql="",
        expected_sql="SELECT name FROM Students WHERE id = 1",
        schema_sql=SCHEMA,
        test_data_sql=TEST_DATA,
        marks=2,
    )
    assert result["status"] == "incorrect", result
    assert result["marks_awarded"] == 0
    print("PASS: Empty answer receives zero marks")


if __name__ == "__main__":
    tests = [
        test_correct_sql,
        test_incorrect_sql,
        test_invalid_sql,
        test_write_query_rejected,
        test_empty_answer,
    ]

    for test in tests:
        test()

    print("\nAll SQL grader tests passed.")