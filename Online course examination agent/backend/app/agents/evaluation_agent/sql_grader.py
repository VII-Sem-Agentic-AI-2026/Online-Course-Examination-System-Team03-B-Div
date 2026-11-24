"""Conservative SQL answer grading using an isolated in-memory SQLite database."""

import sqlite3
from typing import Any


def grade_sql_answer(
    student_sql: str,
    expected_sql: str,
    schema_sql: str,
    test_data_sql: str = "",
    marks: float = 1.0,
) -> dict[str, Any]:
    """
    Compare student and expected SQL query results.

    schema_sql and test_data_sql must come from trusted question-author
    data, never from the student's submitted answer.

    Only read-only SELECT queries are supported. This function is a
    grading helper, not a complete hostile-code security sandbox.
    """

    def result(
        status: str,
        awarded: float,
        feedback: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "marks_awarded": round(awarded, 2),
            "total_marks": round(max(0.0, marks), 2),
            "feedback": feedback,
        }

    if not isinstance(student_sql, str) or not student_sql.strip():
        return result("incorrect", 0.0, "No SQL answer submitted.")

    if not isinstance(expected_sql, str) or not expected_sql.strip():
        return result(
            "pending_review",
            0.0,
            "No trusted expected SQL answer is available.",
        )

    # Validate the trusted setup separately from the student query.
    connection = sqlite3.connect(":memory:")

    try:
        connection.execute("PRAGMA query_only = OFF")
        connection.executescript(schema_sql)

        if test_data_sql.strip():
            connection.executescript(test_data_sql)

        # Both student and reference queries must be read-only SELECTs.
        def is_select_query(sql: str) -> bool:
            stripped = sql.strip()
            if stripped.endswith(";"):
                stripped = stripped[:-1].rstrip()

            if not stripped:
                return False

            # Permit a single SELECT or WITH ... SELECT statement.
            first_word = stripped.split(None, 1)[0].upper()
            return first_word in {"SELECT", "WITH"} and ";" not in stripped

        if not is_select_query(student_sql):
            return result(
                "rejected",
                0.0,
                "Only a single read-only SELECT query is supported.",
            )

        if not is_select_query(expected_sql):
            return result(
                "pending_review",
                0.0,
                "The trusted reference query is not a supported SELECT.",
            )

        # SQLite's authorizer denies data modification and schema changes
        # while either submitted or reference query is executed.
        denied_actions = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
        }

        def authorizer(action, arg1, arg2, database, source):
            if action in denied_actions:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        connection.execute("PRAGMA query_only = ON")

        try:
            expected_rows = connection.execute(expected_sql).fetchall()
            student_rows = connection.execute(student_sql).fetchall()
        except sqlite3.Error:
            return result(
                "incorrect",
                0.0,
                "SQL execution failed against the provided test database.",
            )

        # Row ordering is ignored. Duplicate rows are preserved.
        expected_rows = sorted(
            (tuple(row) for row in expected_rows),
            key=repr,
        )
        student_rows = sorted(
            (tuple(row) for row in student_rows),
            key=repr,
        )

        if student_rows == expected_rows:
            return result("correct", max(0.0, marks), "Query results match.")

        return result(
            "incorrect",
            0.0,
            "Query results do not match the expected results.",
        )

    except sqlite3.Error:
        return result(
            "pending_review",
            0.0,
            "The trusted SQL schema or test data could not be initialized.",
        )
    finally:
        connection.close()