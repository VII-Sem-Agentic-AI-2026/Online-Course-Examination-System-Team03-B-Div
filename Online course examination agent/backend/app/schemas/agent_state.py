from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):

    run_id: str

    # Student identity
    student: Dict[str, Any]

    # Examination information
    exam_id: str
    exam_session: Dict[str, Any]

    # Overall requirement/goal
    goal: str
    requirements: Dict[str, Any]

    # Current orchestration status
    current_stage: str
    current_agent: str

    # Question-related data
    # Original questions, including answer keys
    questions: List[Dict[str, Any]]

    # Student-facing questions without sensitive fields
    student_questions: List[Dict[str, Any]]

    # Professor notes retrieval
    retrieved_context: str
    retrieved_chunks: List[Dict[str, Any]]

    # Question source verification
    grounding_results: List[Dict[str, Any]]

    # Validation information
    validation_results: List[Dict[str, Any]]
    validation_status: str

    # Student answers
    answers: List[Dict[str, Any]]
    pending_answers: List[Dict[str, Any]]

    # Exam submission
    submit_exam: bool

    # Evaluation information
    evaluation_results: List[Dict[str, Any]]

    # Final system output
    final_result: Optional[Dict[str, Any]]

    # Error and retry information
    retry_count: int
    errors: List[str]

    # Execution trace
    trace: List[Dict[str, Any]]

    # Agentic reasoning cycle
    perception: Dict[str, Any]
    plan: Dict[str, Any]
    action: Dict[str, Any]
    observation: Dict[str, Any]
    revision: Dict[str, Any]

    # Number of agentic iterations
    iteration_count: int