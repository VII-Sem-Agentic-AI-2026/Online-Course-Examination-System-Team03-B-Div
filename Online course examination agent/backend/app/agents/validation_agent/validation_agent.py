import re

from typing import Any, Dict

from backend.app.schemas.agent_state import AgentState


class ValidationAgent:
    """
    Validate examination questions.

    In notes-only mode, every question must:
    1. Come from the professor's uploaded notes.
    2. Reference valid retrieved source chunks.
    3. Contain an exact supporting quote from those chunks.
    4. Match the requested subject and difficulty.
    """

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip()

    def run(self, state: AgentState) -> Dict[str, Any]:

        questions = state.get("questions", [])
        requirements = state.get("requirements", {})

        notes_only = requirements.get("notes_only", False)
        retrieved_chunks = state.get("retrieved_chunks", [])

        validation_results = []
        valid_questions = []

        duplicate_indexes = self._find_duplicate_questions(questions)

        # --------------------------------------------------------
        # 1. Validate each question individually
        # --------------------------------------------------------

        for index, question in enumerate(questions, start=1):

            errors = self._validate_question(
                question,
                requirements
            )

            zero_based_index = index - 1

            if zero_based_index in duplicate_indexes:
                errors.append("Duplicate question detected.")

            # ----------------------------------------------------
            # 2. Professor-notes-only source validation
            # ----------------------------------------------------

            if notes_only:
                source_errors = self._validate_source(
                    question,
                    retrieved_chunks,
                    requirements
                )

                errors.extend(source_errors)

            result = {
                "question_index": index,
                "valid": len(errors) == 0,
                "errors": errors,
            }

            validation_results.append(result)

            if not errors:
                valid_questions.append(question)

        # --------------------------------------------------------
        # 3. Validate requested question distribution
        # --------------------------------------------------------

        question_mix = requirements.get("question_mix")

        mix_errors = []

        expected_mix = None
        actual_mix = None

        if question_mix:

            expected_mix = {
                "normal_mcq": int(question_mix.get("normal_mcq", 0)),
                "scenario_mcq": int(question_mix.get("scenario_mcq", 0)),
                "coding": int(question_mix.get("coding", 0)),
            }

            actual_mix = {
                "normal_mcq": 0,
                "scenario_mcq": 0,
                "coding": 0,
            }

            for question in questions:
                question_type = question.get("question_type")

                if question_type in actual_mix:
                    actual_mix[question_type] += 1

            for question_type, expected_count in expected_mix.items():

                actual_count = actual_mix[question_type]

                if actual_count != expected_count:
                    mix_errors.append(
                        f"{question_type}: expected {expected_count}, "
                        f"but received {actual_count}."
                    )

        # --------------------------------------------------------
        # 4. Validate total question count
        # --------------------------------------------------------

        count_errors = []

        expected_count = requirements.get("number_of_questions")

        if expected_count is not None and len(questions) != int(expected_count):
            count_errors.append(
                f"Expected {expected_count} questions, "
                f"but received {len(questions)}."
            )

        # --------------------------------------------------------
        # 5. Overall validation status
        # --------------------------------------------------------

        all_questions_valid = (
            len(valid_questions) == len(questions)
            and len(questions) > 0
        )

        mix_valid = len(mix_errors) == 0
        count_valid = len(count_errors) == 0

        all_valid = (
            all_questions_valid
            and mix_valid
            and count_valid
        )

        # Fail closed: do not pass partial question sets.
        final_questions = valid_questions if all_valid else []

        return {
            "current_agent": "validation_agent",

            "action": {
                "type": "validate_questions",
                "question_count": len(questions),
                "valid_count": len(valid_questions),
                "invalid_count": len(questions) - len(valid_questions),
                "status": "passed" if all_valid else "failed",
                "notes_only": notes_only,
                "expected_mix": expected_mix,
                "actual_mix": actual_mix,
                "mix_errors": mix_errors,
                "count_errors": count_errors,
            },

            "validation_results": validation_results,

            "questions": final_questions,

            "trace_entry": {
                "agent": "validation_agent",
                "action": "validate_questions",
                "question_count": len(questions),
                "valid_count": len(valid_questions),
                "invalid_count": len(questions) - len(valid_questions),
                "mix_valid": mix_valid,
                "count_valid": count_valid,
                "notes_only": notes_only,
                "status": "passed" if all_valid else "failed",
            },
        }

    # ============================================================
    # SOURCE VALIDATION
    # ============================================================

    def _validate_source(
        self,
        question: Dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        requirements: Dict[str, Any],
    ) -> list[str]:

        errors = []

        # Every question must identify professor notes as its source.

        if question.get("source") != "professor_notes":
            errors.append(
                "Question was not identified as coming from professor notes."
            )

        source_chunk_ids = question.get("source_chunk_ids")
        supporting_quote = question.get("supporting_quote")

        if not isinstance(source_chunk_ids, list) or not source_chunk_ids:
            errors.append(
                "Question is missing valid source_chunk_ids."
            )
            return errors

        if not isinstance(supporting_quote, str) or not supporting_quote.strip():
            errors.append(
                "Question is missing its supporting quote."
            )
            return errors

        # Build lookup of retrieved chunks.

        chunk_lookup = {
            str(chunk.get("chunk_id")): chunk
            for chunk in retrieved_chunks
            if chunk.get("chunk_id") is not None
        }

        # Verify that every referenced chunk was actually retrieved.

        invalid_ids = [
            chunk_id
            for chunk_id in source_chunk_ids
            if str(chunk_id) not in chunk_lookup
        ]

        if invalid_ids:
            errors.append(
                f"Invalid source chunk IDs: {invalid_ids}"
            )
            return errors

        matching_chunks = [
            chunk_lookup[str(chunk_id)]
            for chunk_id in source_chunk_ids
        ]

        # Verify document ownership against the selected documents.

        selected_document_ids = {
            str(document_id)
            for document_id in requirements.get("document_ids", [])
        }

        for chunk in matching_chunks:

            document_id = str(chunk.get("document_id"))

            if selected_document_ids and document_id not in selected_document_ids:
                errors.append(
                    "Question references a document that was not selected."
                )
                break

        # Supporting quote must be an exact substring of a cited chunk.

        normalized_quote = self._normalize_text(
            supporting_quote
        )

        quote_found = any(
            normalized_quote in self._normalize_text(
                chunk.get("text", "")
            )
            for chunk in matching_chunks
        )

        if not quote_found:
            errors.append(
                "Supporting quote does not exactly match the referenced professor notes."
            )

        return errors

    # ============================================================
    # DUPLICATE VALIDATION
    # ============================================================

    def _find_duplicate_questions(
        self,
        questions: list[dict[str, Any]],
    ) -> set[int]:

        seen = {}
        duplicates = set()

        for index, question in enumerate(questions):

            text = question.get("question", "").strip().lower()

            if not text:
                continue

            if text in seen:
                duplicates.add(index)
            else:
                seen[text] = index

        return duplicates

    # ============================================================
    # STRUCTURAL AND REQUIREMENT VALIDATION
    # ============================================================

    def _validate_question(
        self,
        question: Dict[str, Any],
        requirements: Dict[str, Any],
    ) -> list[str]:

        errors = []

        # --------------------------------------------------------
        # Common required fields
        # --------------------------------------------------------

        if not question.get("question"):
            errors.append("Question text is missing.")

        if not question.get("subject"):
            errors.append("Subject is missing.")

        if not question.get("difficulty"):
            errors.append("Difficulty is missing.")

        question_type = question.get("question_type")

        if not question_type:
            errors.append("Question type is missing.")

        # --------------------------------------------------------
        # Subject validation
        # --------------------------------------------------------

        expected_subject = requirements.get("subject")

        if (
            expected_subject
            and question.get("subject", "").strip().lower()
            != expected_subject.strip().lower()
        ):
            errors.append(
                "Question subject does not match the requested subject."
            )

        # --------------------------------------------------------
        # Difficulty validation
        # --------------------------------------------------------

        expected_difficulty = requirements.get("difficulty")

        if (
            expected_difficulty
            and question.get("difficulty", "").strip().upper()
            != expected_difficulty.strip().upper()
        ):
            errors.append(
                "Question difficulty does not match the requested difficulty."
            )

        # --------------------------------------------------------
        # MCQ validation
        # --------------------------------------------------------

        if question_type in {"normal_mcq", "scenario_mcq"}:

            options = question.get("options")

            if not isinstance(options, dict):
                errors.append("MCQ options must be a dictionary.")

            else:
                expected_options = {"A", "B", "C", "D"}

                if set(options.keys()) != expected_options:
                    errors.append(
                        "MCQ must contain exactly A, B, C and D options."
                    )

                for key in expected_options:
                    if not options.get(key):
                        errors.append(
                            f"MCQ option {key} is empty."
                        )

            correct_answer = question.get("correct_answer")

            if correct_answer not in {"A", "B", "C", "D"}:
                errors.append(
                    "MCQ correct_answer must be A, B, C or D."
                )

            if not question.get("explanation"):
                errors.append("MCQ explanation is missing.")

        # --------------------------------------------------------
        # Coding question validation
        # --------------------------------------------------------

        elif question_type == "coding":

            expected_answer = question.get("expected_answer")

            if not expected_answer:
                errors.append(
                    "Coding question expected_answer is missing."
                )

            options = question.get("options", {})

            if options not in ({}, None):
                errors.append(
                    "Coding questions should not contain MCQ options."
                )

        else:
            errors.append(
                f"Unsupported question type: {question_type}"
            )

        return errors