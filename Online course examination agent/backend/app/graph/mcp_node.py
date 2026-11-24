import asyncio
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.app.document_processing.vector_store import search_chunks


# ============================================================
# LEGACY MCP QUESTION BANK
# Used only when notes_only is False.
# ============================================================

async def _call_mcp_tool(
    subject: str,
    topic: str | None,
    difficulty: str,
    count: int,
):

    server_params = StdioServerParameters(
        command="python",
        args=[
            "-m",
            "backend.app.mcp.server",
        ],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()

            result = await session.call_tool(
                "get_question_bank",
                arguments={
                    "subject": subject,
                    "topic": topic,
                    "difficulty": difficulty,
                    "count": count,
                },
            )

            return result


# ============================================================
# MAIN MCP / NOTES RETRIEVAL NODE
# ============================================================

def mcp_node(state) -> dict[str, Any]:

    requirements = state.get("requirements", {})

    notes_only = requirements.get("notes_only", False)

    retrieval_request = state.get("action", {}).get(
        "retrieval_request",
        {},
    )

    subject = retrieval_request.get(
        "subject",
        requirements.get("subject"),
    )

    topic = retrieval_request.get(
        "topic",
        requirements.get("topic"),
    )

    difficulty = retrieval_request.get(
        "difficulty",
        requirements.get("difficulty", "L1"),
    )

    count = retrieval_request.get(
        "count",
        requirements.get(
            "number_of_questions",
            5,
        ),
    )

    # ========================================================
    # PATH 1: PROFESSOR NOTES CONTENT RETRIEVAL
    # ========================================================

    if notes_only:

        teacher_id = requirements.get("teacher_id")
        document_ids = requirements.get("document_ids", [])

        if not teacher_id or not document_ids:
            return {
                "questions": [],
                "retrieved_chunks": [],
                "retrieved_context": "",
                "errors": list(state.get("errors", []))
                + [
                    "Notes-only retrieval requires a teacher ID "
                    "and selected document IDs."
                ],
                "observation": {
                    **state.get("observation", {}),
                    "notes_retrieval": {
                        "available": False,
                        "error": "Missing teacher ID or document IDs.",
                    },
                },
            }

        if not subject:
            return {
                "questions": [],
                "retrieved_chunks": [],
                "retrieved_context": "",
                "errors": list(state.get("errors", []))
                + ["Subject is required for notes retrieval."],
            }

        # Build a semantic search query.
        query_parts = [
            f"Subject: {subject}",
        ]

        if topic:
            query_parts.append(f"Topic: {topic}")

        if difficulty:
            query_parts.append(f"Difficulty: {difficulty}")

        query_parts.append(
            "Find definitions, explanations, concepts, examples "
            "and important learning material relevant to generating "
            "examination questions."
        )

        query = " ".join(query_parts)

        try:

            # Retrieve only selected teacher-owned documents.
            top_k = max(8, min(int(count) * 3, 30))

            retrieved_chunks = search_chunks(
                query=query,
                teacher_id=int(teacher_id),
                subject=subject.strip(),
                document_ids=document_ids,
                top_k=top_k,
            )

            if not retrieved_chunks:
                return {
                    "questions": [],
                    "retrieved_chunks": [],
                    "retrieved_context": "",
                    "errors": list(state.get("errors", []))
                    + [
                        "No relevant professor-note content was found. "
                        "Question generation has been stopped."
                    ],
                    "observation": {
                        **state.get("observation", {}),
                        "notes_retrieval": {
                            "available": False,
                            "error": "No relevant note chunks found.",
                        },
                    },
                }

            # Build context for the Question Generation Agent.
            context_parts = []

            for chunk in retrieved_chunks:

                context_parts.append(
                    f"""
                    [SOURCE DOCUMENT: {chunk['document_id']}]
                    [SOURCE CHUNK: {chunk['chunk_id']}]

                    {chunk['text']}
                    """
                )

            retrieved_context = "\n\n".join(context_parts)

            trace = state.get("trace", [])

            return {
                "questions": [],
                "retrieved_chunks": retrieved_chunks,
                "retrieved_context": retrieved_context,
                "errors": list(state.get("errors", [])),
                "observation": {
                    **state.get("observation", {}),
                    "notes_retrieval": {
                        "available": True,
                        "source": "professor_notes",
                        "document_count": len(set(
                            chunk["document_id"]
                            for chunk in retrieved_chunks
                        )),
                        "chunk_count": len(retrieved_chunks),
                    },
                },
                "trace": trace + [
                    {
                        "agent": "notes_retrieval",
                        "action": "search_professor_notes",
                        "status": "success",
                        "chunk_count": len(retrieved_chunks),
                    }
                ],
            }

        except Exception as exc:

            return {
                "questions": [],
                "retrieved_chunks": [],
                "retrieved_context": "",
                "errors": list(state.get("errors", []))
                + [
                    f"Professor notes retrieval failed: {str(exc)}"
                ],
                "observation": {
                    **state.get("observation", {}),
                    "notes_retrieval": {
                        "available": False,
                        "error": str(exc),
                    },
                },
            }

    # ========================================================
    # PATH 2: LEGACY QUESTION BANK
    # ========================================================

    if not subject:
        return {
            "questions": [],
            "errors": list(state.get("errors", []))
            + ["Subject is required for question retrieval."],
        }

    try:

        result = asyncio.run(
            _call_mcp_tool(
                subject=subject,
                topic=topic,
                difficulty=difficulty,
                count=count,
            )
        )

        structured_content = getattr(
            result,
            "structured_content",
            None,
        )

        if not structured_content:
            raise RuntimeError(
                "MCP returned no structured question data."
            )

        questions = structured_content.get("questions", [])

        for question in questions:
            question.setdefault("question_type", "normal_mcq")

        return {
            "questions": questions,
            "observation": {
                **state.get("observation", {}),
                "mcp": {
                    "available": True,
                    "tool": "get_question_bank",
                    "count": len(questions),
                    "source": structured_content.get(
                        "source",
                        "question_bank",
                    ),
                },
            },
        }

    except Exception as exc:

        return {
            "questions": [],
            "errors": list(state.get("errors", []))
            + [f"MCP question retrieval failed: {str(exc)}"],
        }