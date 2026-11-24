from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Header,
    File,
    Form,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.database import SessionLocal
from backend.app.models import (
    User,
    Exam,
    ExamAttempt,
    ProctoringEvent,
)
from backend.app.exampilot_persistence import sync_state

from backend.app.agents.exam_session_agent.exam_session_agent import ExamSessionAgent
from backend.app.graph.exam_graph import evaluation_node, exam_graph
from backend.app.schemas.exam_request import ExamRequest
from backend.app.schemas.exam_session import ExamSession, ExamSessionStatus

from backend.app.document_processing.text_extractor import (
    extract_text,
    DocumentExtractionError,
)
from backend.app.document_processing.chunker import chunk_text
from backend.app.document_processing.vector_store import save_chunks
from backend.app.exampilot_recordings import create_recordings_router

from copy import deepcopy


from uuid import uuid5, NAMESPACE_URL

from backend.app.demo_exam import (
    DEMO_QUESTIONS,
    DEMO_SUBJECT,
    DEMO_TOPIC,
    grade_demo_attempt,
)



app = FastAPI(
    title="Online Course Examination System",
    description="Exam generation, session management, authentication, and automated evaluation.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://exampilot-frontend-7cf2.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_agent = ExamSessionAgent()
sessions: dict[str, dict[str, Any]] = {}
sessions_lock = Lock()


EXAMPILOT_DEMO_MODE = (
    os.getenv("EXAMPILOT_DEMO_MODE", "false").lower()
    == "true"
)


def require_demo_mode() -> None:
    if not EXAMPILOT_DEMO_MODE:
        raise HTTPException(
            status_code=404,
            detail="Development demo exams are disabled",
        )


SECRET_FILE = Path(__file__).resolve().parent / ".auth_secret"
AUTH_SECRET = os.getenv("AUTH_SECRET_KEY")

if not AUTH_SECRET:
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
    AUTH_SECRET = SECRET_FILE.read_text(encoding="utf-8").strip()

bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Professor notes storage (SQLite, separate from PostgreSQL exam data)
# ---------------------------------------------------------------------------

NOTES_DB = Path(__file__).resolve().parent / "notes.db"
NOTES_STORAGE_DIR = Path(
    os.getenv(
        "NOTES_STORAGE_DIR",
        str(Path(__file__).resolve().parent / "uploads" / "teacher_notes"),
    )
).resolve()
MAX_NOTE_FILE_SIZE = 25 * 1024 * 1024
ALLOWED_NOTE_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}


def init_notes_db() -> None:
    """Initialize notes metadata storage independently of PostgreSQL users."""
    NOTES_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(NOTES_DB) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS teacher_notes (
                document_id TEXT PRIMARY KEY,
                teacher_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                file_extension TEXT NOT NULL,
                content_type TEXT,
                file_size INTEGER NOT NULL,
                subject TEXT NOT NULL,
                topic TEXT,
                storage_path TEXT NOT NULL,
                processing_status TEXT NOT NULL DEFAULT 'uploaded',
                extracted_text TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS idx_teacher_notes_owner_subject
               ON teacher_notes(teacher_id, subject)"""
        )
        db.commit()


init_notes_db()


# ---------------------------------------------------------------------------
# Authentication models and helpers
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=120)
    roll_number: int = Field(..., ge=1)
    usn: str = Field(..., min_length=1, max_length=50)
    division: str = Field(..., min_length=1, max_length=30)
    role: str = Field(default="student", pattern="^(student|teacher)$")


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class ScheduleRequest(BaseModel):
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    duration_minutes: int = Field(default=30, ge=1, le=1440)


# ============================================================
# PROCTORING - REQUEST SCHEMA
# ============================================================

class ExamClientRequest(BaseModel):
    client_id: str = Field(..., min_length=16, max_length=100)


class StartExamRequest(BaseModel):
    consent_accepted: bool

class ProctoringEventRequest(BaseModel):
    event_type: str
    details: dict[str, Any] = Field(default_factory=dict)


ALLOWED_PROCTORING_EVENTS = {
    "fullscreen_exit",
    "tab_switch",
    "window_blur",
    "copy_attempt",
    "paste_attempt",
    "context_menu",

    # AI observations — for teacher review only
    "ai_face_absent",
    "ai_multiple_faces",
    "ai_mobile_phone",
}

BROWSER_VIOLATION_EVENTS = {
    "fullscreen_exit",
    "tab_switch",
    "window_blur",
    "copy_attempt",
    "paste_attempt",
    "context_menu",
}


# ============================================================
# PROCTORING WARNING POLICY
# ============================================================

PROCTORING_TERMINATION_THRESHOLD = 4
PROCTORING_INCIDENT_WINDOW_SECONDS = 2.0


def calculate_proctoring_warning_status(events):
    """
    Group closely spaced browser events into incidents.

    Events are ordered by their server timestamps.
    Multiple events within two seconds of an incident's
    first event count as one incident.

    This is an initial policy for development and testing.
    """

    ordered_events = sorted(
        [
            event
            for event in events
            if event.event_type in BROWSER_VIOLATION_EVENTS
        ],
        key=lambda event: (event.occurred_at, event.id),
    )

    incidents = []

    for event in ordered_events:
        event_time = event.occurred_at

        if not incidents:
            incidents.append([event])
            continue

        first_event = incidents[-1][0]

        elapsed = (
            event_time - first_event.occurred_at
        ).total_seconds()

        if elapsed < PROCTORING_INCIDENT_WINDOW_SECONDS:
            incidents[-1].append(event)
        else:
            incidents.append([event])

    count = len(incidents)

    if count == 0:
        level = "clear"
        warning = "No security warnings recorded."

    elif count == 1:
        level = "warning"
        warning = "First warning: Follow examination rules."

    elif count == 2:
        level = "warning"
        warning = "Second warning: Further violations may terminate your exam."

    elif count == 3:
        level = "final_warning"
        warning = "Final warning: The next incident reaches the termination threshold."

    else:
        level = "termination_threshold"
        warning = "Security violation limit reached. Examination flagged for termination."

    return {
        "incident_count": count,
        "total_events": len(ordered_events),
        "warning_level": level,
        "warning_message": warning,
        "termination_threshold_reached": (
            count >= PROCTORING_TERMINATION_THRESHOLD
        ),
    }


class AnswerRequest(BaseModel):
    question_id: str = Field(..., min_length=1)
    answer: str = Field(default="", max_length=100_000)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, expected_digest = stored_hash.split(":", 1)
        actual_digest = hash_password(
            password, bytes.fromhex(salt_hex)
        ).split(":", 1)[1]
        return hmac.compare_digest(actual_digest, expected_digest)
    except (ValueError, TypeError):
        return False


def create_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": user["email"],
        "role": user["role"],
        "exp": int(time.time()) + 8 * 60 * 60,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        AUTH_SECRET.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def safe_user(row: User) -> dict[str, Any]:
    return {
        "id": row.id,
        "email": row.email,
        "name": row.name,
        "role": row.role,
        "roll_number": row.roll_number,
        "usn": row.usn,
        "division": row.division,
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Please log in to continue")

    try:
        encoded, supplied_signature = credentials.credentials.split(".", 1)
        expected_signature = hmac.new(
            AUTH_SECRET.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("Invalid token signature")

        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii"))
        )

        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("Token expired")

        email = str(payload["sub"]).lower()
        token_role = str(payload["role"])

        with SessionLocal() as db:
            row = db.scalar(select(User).where(User.email == email))

        if row is None or row.role != token_role:
            raise ValueError("User or role no longer valid")

        return safe_user(row)

    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        raise HTTPException(
            status_code=401, detail="Invalid or expired login session"
        )


def require_role(*allowed_roles: str):
    def dependency(user: dict[str, Any] = Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="Your account does not have permission for this action",
            )
        return user
    

    return dependency

# ============================================================
# AUDIO/VIDEO RECORDING ENDPOINTS
# Permanent ExamPilot feature
# ============================================================

app.include_router(
    create_recordings_router(get_current_user)
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def public_session(state: dict[str, Any]) -> dict[str, Any]:
    """Return student-safe exam data; never expose answer keys."""
    session = state.get("exam_session") or {}
    questions = state.get("student_questions") or []

    return {
        "session_id": session.get("session_id"),
        "exam_id": session.get("exam_id"),
        "status": session.get("status"),
        "proctoring_terminated": bool(
    state.get("_proctoring_terminated", False)
),
        "started_at": session.get("started_at"),
        "ends_at": session.get("ends_at"),
        "total_questions": session.get("total_questions", len(questions)),
        "answered_questions": session.get("answered_questions", 0),
        "questions": questions,
    }


def session_question_ids(state: dict[str, Any]) -> set[str]:
    """Accept IDs from the student-safe question list, with a fallback."""
    questions = state.get("student_questions") or state.get("questions") or []
    return {
        str(question.get("question_id") or question.get("id"))
        for question in questions
        if question.get("question_id") or question.get("id")
    }


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _exam_schedule(assignment_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        exam = db.get(Exam, assignment_id)
        if exam is None:
            raise HTTPException(404, "Exam assignment not found")
        return {
            "scheduled_start_at": exam.scheduled_start_at,
            "scheduled_end_at": exam.scheduled_end_at,
            "duration_minutes": exam.duration_minutes,
        }


def _save_state(state: dict[str, Any]) -> None:
    """Persist full existing graph state without altering evaluator behavior."""
    assignment_id = str(state["_assignment_id"])
    with SessionLocal.begin() as db:
        if state.get("_is_assignment"):
            exam = db.get(Exam, assignment_id)
            if exam is None:
                raise RuntimeError("Exam record must exist before saving its state")
            exam.generation_state = json.loads(json.dumps(state, default=str))
            sync_state(db, state)
        else:
            sid = str((state.get("exam_session") or {}).get("session_id"))
            attempt = db.get(ExamAttempt, sid)
            if attempt is None:
                raise RuntimeError("Attempt record must exist before saving its state")
            attempt.session_state = json.loads(json.dumps(state, default=str))
            sync_state(db, state, attempt)
            session = state.get("exam_session") or {}
            attempt.status = str(session.get("status") or attempt.status)
            if attempt.status in ("submitted", "evaluated", "completed") and attempt.submitted_at is None:
                attempt.submitted_at = datetime.now(timezone.utc)


def _hydrate_sessions() -> None:
    """Restore assignments and attempts on restart; DB is the durable source."""
    with SessionLocal() as db:
        for exam in db.scalars(select(Exam)).all():
            if exam.generation_state:
                sessions[exam.id] = exam.generation_state
        for attempt in db.scalars(select(ExamAttempt)).all():
            if attempt.session_state:
                sessions[attempt.id] = attempt.session_state


# Initialize database tables before restoring sessions
from backend.app import models
from backend.app.database import Base, engine

Base.metadata.create_all(bind=engine)

_hydrate_sessions()

def load_session(session_id: str) -> dict[str, Any]:
    """
    Load the latest examination state from PostgreSQL.
    """

    with SessionLocal() as db:
        attempt = db.get(ExamAttempt, session_id)

        if attempt is not None and attempt.session_state:
            state = deepcopy(attempt.session_state)
            sessions[session_id] = state
            return state

        exam = db.get(Exam, session_id)

        if exam is not None and exam.generation_state:
            state = deepcopy(exam.generation_state)
            sessions[session_id] = state
            return state

    state = sessions.get(session_id)

    if state is not None:
        return state

    raise HTTPException(
        status_code=404,
        detail="Exam session not found",
    )


@app.put("/api/teacher/exams/{assignment_id}/schedule")
def set_exam_schedule(
    assignment_id: str,
    request: ScheduleRequest,
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    start = _utc(request.scheduled_start_at)
    end = _utc(request.scheduled_end_at)
    if start and end and end <= start:
        raise HTTPException(422, "Scheduled end must be after scheduled start")
    with SessionLocal.begin() as db:
        exam = db.get(Exam, assignment_id)
        if exam is None:
            raise HTTPException(404, "Exam not found")
        if exam.teacher_id != user["id"]:
            raise HTTPException(403, "You do not own this exam")
        if db.scalar(select(ExamAttempt.id).where(ExamAttempt.exam_id == assignment_id).limit(1)):
            raise HTTPException(409, "Cannot change timing after an attempt has started")
        exam.scheduled_start_at = start
        exam.scheduled_end_at = end
        exam.duration_minutes = request.duration_minutes
    return {"assignment_id": assignment_id, "scheduled_start_at": start,
            "scheduled_end_at": end, "duration_minutes": request.duration_minutes}


def _check_start_window(assignment_id: str) -> dict[str, Any]:
    schedule = _exam_schedule(assignment_id)
    now = datetime.now(timezone.utc)
    if schedule["scheduled_start_at"] and now < _utc(schedule["scheduled_start_at"]):
        raise HTTPException(403, "Exam has not started yet")
    if schedule["scheduled_end_at"] and now >= _utc(schedule["scheduled_end_at"]):
        raise HTTPException(409, "Exam scheduling window has closed")
    return schedule


def _check_attempt_deadline(state: dict[str, Any]) -> None:
    session = state.get("exam_session") or {}
    ends = session.get("ends_at")
    if ends:
        deadline = _utc(datetime.fromisoformat(str(ends).replace("Z", "+00:00")))
        if datetime.now(timezone.utc) >= deadline:
            raise HTTPException(409, "Exam time has expired")



# ============================================================
# EXAM CLIENT PROTECTION
# ============================================================

EXAM_HEARTBEAT_TIMEOUT_SECONDS = 45


def verify_exam_client(
    state: dict[str, Any],
    client_id: str | None,
) -> None:
    registered = state.get("_exam_client_id")

    if not registered or client_id != registered:
        raise HTTPException(
            status_code=409,
            detail="This exam is active in another browser session.",
        )


def verify_active_student_attempt(
    state: dict[str, Any],
    user: dict[str, Any],
) -> None:
    if state.get("_is_assignment"):
        raise HTTPException(409, "Start the examination first")

    if not _can_access_attempt(state, user):
        raise HTTPException(403, "Not your examination attempt")

    if state["exam_session"]["status"] != "in_progress":
        raise HTTPException(409, "This examination has already ended")



# ============================================================
# SHARED EXAM FINALIZATION
# Called while sessions_lock is already held.
# ============================================================

def finalize_exam_locked(
    session_id: str,
    *,
    proctoring_terminated: bool = False,
) -> dict[str, Any]:

    state = load_session(session_id)

    if state.get("_is_assignment"):
        raise HTTPException(
            409, "This is not a student exam attempt"
        )

    session = ExamSession.model_validate(
        state["exam_session"]
    )

    if session.status != ExamSessionStatus.IN_PROGRESS:
        raise HTTPException(
            409, "This examination has already ended"
        )

    # Use the original ExamPilot submission mechanism.
    # It also handles exams whose time has expired.
    session = session_agent.submit_session(session)

    state["exam_session"] = session.model_dump(mode="json")

    state["answers"] = [
        answer.model_dump(mode="json")
        for answer in session.answers.values()
    ]

    if proctoring_terminated:
        state["_proctoring_terminated"] = True
        state["_proctoring_termination_reason"] = (
            "Security violation limit reached"
        )

    # Persist the locked attempt BEFORE evaluation.
    _save_state(state)
    sessions[session_id] = state

    try:
        
        evaluation = (
            grade_demo_attempt(state)
            if state.get("_demo_exam")
            else evaluation_node(state)
        )


        if evaluation.get("current_stage") == "error":
            error_message = str(
                evaluation.get(
                    "errors",
                    ["Evaluation failed"]
                )
            )
            raise RuntimeError(error_message)

        state.update(evaluation)
        state["_evaluation_pending"] = False

        _save_state(state)
        sessions[session_id] = state

    except Exception as exc:
        # Keep the exam locked even if grading fails.
        state["_evaluation_pending"] = True
        state["_evaluation_error"] = str(exc)

        _save_state(state)
        sessions[session_id] = state

    return {
        "message": (
            "Exam automatically terminated"
            if proctoring_terminated
            else "Exam submitted"
        ),
        "exam_terminated": proctoring_terminated,
        "status": state["exam_session"]["status"],
        "evaluation_pending": state.get(
            "_evaluation_pending", False
        ),
        "result": state.get("final_result"),
        "evaluation_results": state.get(
            "evaluation_results", []
        ),
    }

# ---------------------------------------------------------------------------
# Basic endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "Online Course Examination API",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "api": "running"}


# ---------------------------------------------------------------------------
# Authentication endpoints
# ---------------------------------------------------------------------------

@app.post("/api/auth/register", status_code=201)
def register(request: RegisterRequest):
    email = request.email.lower().strip()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address")

    try:
        with SessionLocal.begin() as db:
            db.add(User(
                email=email,
                password_hash=hash_password(request.password),
                name=request.name.strip(),
                role=request.role,
                roll_number=request.roll_number if request.role == "student" else None,
                usn=request.usn.strip() if request.role == "student" else None,
                division=request.division.strip() if request.role == "student" else None,
            ))
    except IntegrityError as exc:
        # Only an email uniqueness violation should become HTTP 409.
        # Other integrity failures should remain visible as server errors.
        if getattr(exc.orig, "sqlstate", None) == "23505" and (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "users_email_key"
        ):
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists",
            ) from exc
        raise

    return {"message": "Account created successfully. Please log in."}


@app.post("/api/auth/login")
def login(request: LoginRequest):
    email = request.email.lower().strip()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address")

    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.email == email))

    if row is None or not verify_password(
        request.password, row.password_hash
    ):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    user = safe_user(row)
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "user": user,
    }


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------------------
# Exam endpoints
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Exam endpoints
# ---------------------------------------------------------------------------

def _same_division(a: Any, b: Any) -> bool:
    return str(a or "").strip().upper() == str(b or "").strip().upper()



def _student_attempt_for_assignment(
    assignment_id: str,
    student_email: str,
) -> tuple[str, dict[str, Any]] | None:

    assignment = sessions.get(assignment_id) or {}
    is_demo = bool(assignment.get("_demo_exam"))

    matches = [
        (sid, state)
        for sid, state in sessions.items()
        if (
            not state.get("_is_assignment")
            and state.get("_assignment_id") == assignment_id
            and state.get("_student_email") == student_email
        )
    ]

    if not matches:
        return None

    if not is_demo:
        # Original behavior: only one real attempt.
        return matches[0]

    # Demo behavior: reuse the student's active attempt.
    # When the previous demo attempt has ended, a new
    # one can be created from the assignment.
    active = [
        (sid, state)
        for sid, state in matches
        if (
            state.get("exam_session") or {}
        ).get("status") == "in_progress"
    ]

    if active:
        return active[-1]

    return None



def _can_access_attempt(state: dict[str, Any], user: dict[str, Any]) -> bool:
    if user["role"] == "teacher":
        return state.get("_owner_email") == user["email"]

    return (
        state.get("_student_email") == user["email"]
        and _same_division(
            state.get("_target_division"),
            user.get("division"),
        )
    )



@app.post("/api/dev/demo-exam")
def create_demo_exam(
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """Create or return this teacher's development fixture."""
    require_demo_mode()

    # Stable ID: repeated requests do not create duplicate exams.
    # Create a fresh development exam without calling Gemini.
    # Previous students' attempts and results remain untouched.
    assignment_id = str(uuid4())

    target_division = "A"

    with sessions_lock:
        with SessionLocal.begin() as db:
            existing = db.get(Exam, assignment_id)

            if existing is not None:
                if not existing.generation_state:
                    raise HTTPException(
                        409,
                        "Demo exam record has no saved state",
                    )

                sessions[assignment_id] = existing.generation_state

                return {
                    "message": "Demo exam already exists",
                    "assignment_id": assignment_id,
                    "created": False,
                }

            # This has the same assignment metadata shape
            # used by ExamPilot's existing exam listing.
            state = {
                "_is_assignment": True,
                "_demo_exam": True,
                "_assignment_id": assignment_id,
                "_owner_email": user["email"],
                "_owner_role": "teacher",
                "_target_division": target_division,
                "_subject": DEMO_SUBJECT,
                "_topic": DEMO_TOPIC,
                "_difficulty": "L1",
                "_document_ids": [],
                "requirements": {
                    "teacher_id": user["id"],
                    "notes_only": False,
                    "demo_exam": True,
                },
                "questions": DEMO_QUESTIONS,
                "validated_questions": DEMO_QUESTIONS,
                "student_questions": [],
                "answers": [],
                "evaluation_results": [],
                "final_result": None,
                "exam_session": {
                    "session_id": assignment_id,
                    "exam_id": assignment_id,
                    "status": "assigned",
                    "total_questions": len(DEMO_QUESTIONS),
                    "answered_questions": 0,
                },
            }

            db.add(
                Exam(
                    id=assignment_id,
                    teacher_id=user["id"],
                    division=target_division,
                    subject=DEMO_SUBJECT,
                    topic=DEMO_TOPIC,
                    difficulty="L1",
                    status="assigned",
                    duration_minutes=10,
                    scheduled_start_at=None,
                    scheduled_end_at=None,
                    generation_state=json.loads(
                        json.dumps(state, default=str)
                    ),
                )
            )

        sessions[assignment_id] = state

    return {
        "message": "Reusable demo exam created",
        "assignment_id": assignment_id,
        "created": True,
        "division": target_division,
        "total_questions": len(DEMO_QUESTIONS),
    }


@app.post("/api/exams")
def generate_exam(
    request: ExamRequest,
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """Generate a division examination using only the selected professor notes."""
    try:
        from backend.app.graph.exam_graph import create_exam_state

        target_division = str(request.student.division).strip()
        if not target_division:
            raise HTTPException(422, "Target division is required")

        document_ids = list(dict.fromkeys(request.document_ids or []))
        if not document_ids:
            raise HTTPException(422, "Select at least one professor notes document")

        placeholders = ",".join("?" for _ in document_ids)
        with sqlite3.connect(NOTES_DB) as notes_db:
            notes_db.row_factory = sqlite3.Row
            documents = notes_db.execute(
                f"""SELECT document_id, subject, processing_status
                    FROM teacher_notes
                    WHERE teacher_id = ? AND document_id IN ({placeholders})""",
                [user["id"], *document_ids],
            ).fetchall()

        if len(documents) != len(document_ids):
            raise HTTPException(
                403,
                "One or more selected documents are unavailable or do not belong to you",
            )

        for document in documents:
            if document["subject"].strip().lower() != request.subject.strip().lower():
                raise HTTPException(422, "Selected notes do not match the examination subject")
            if document["processing_status"] != "processed":
                raise HTTPException(422, "All selected notes must be successfully processed")

        initial_state = create_exam_state(request)
        initial_state.setdefault("requirements", {})
        initial_state["requirements"].update({
            "teacher_id": user["id"],
            "document_ids": document_ids,
            "notes_only": True,
        })

        result = exam_graph.invoke(initial_state)
        if result.get("current_stage") == "error":
            raise HTTPException(
                500,
                detail={
                    "message": "Exam workflow failed",
                    "errors": result.get("errors", []),
                },
            )

        session_data = result.get("exam_session") or {}
        assignment_id = session_data.get("session_id")
        if not assignment_id:
            raise HTTPException(500, "Workflow did not create an examination")

        result["_is_assignment"] = True
        result["_assignment_id"] = str(assignment_id)
        result["_owner_email"] = user["email"]
        result["_owner_role"] = "teacher"
        result["_target_division"] = target_division
        result["_subject"] = request.subject
        result["_topic"] = request.topic
        result["_difficulty"] = request.difficulty
        result["_document_ids"] = document_ids
        result.pop("_student_roll_number", None)
        result.pop("_student_usn", None)
        result.pop("_student_name", None)

        # Persist the generated assignment in PostgreSQL, as in the teammate's
        # scheduling/persistence implementation.
                # Convert scheduling times to UTC before storing.
        scheduled_start = _utc(request.scheduled_start_at)
        scheduled_end = _utc(request.scheduled_end_at)

        if (
            scheduled_start
            and scheduled_end
            and scheduled_end <= scheduled_start
        ):
            raise HTTPException(
                422,
                "Scheduled end must be after scheduled start."
            )

        with SessionLocal.begin() as db:
            db.add(Exam(
                id=str(assignment_id),
                teacher_id=user["id"],
                division=target_division,
                subject=str(request.subject or ""),
                topic=str(request.topic or ""),
                difficulty=str(request.difficulty or ""),
                status="assigned",
                duration_minutes=request.duration_minutes,
                scheduled_start_at=scheduled_start,
                scheduled_end_at=scheduled_end,
                generation_state=json.loads(json.dumps(result, default=str)),
            ))

            db.flush()

            # Persist generated questions in PostgreSQL.
            sync_state(db, result)

        with sessions_lock:
            sessions[str(assignment_id)] = result

        response = public_session(result)
        response.update({
            "session_id": str(assignment_id),
            "assignment_id": str(assignment_id),
            "division": target_division,
            "subject": request.subject,
            "topic": request.topic,
            "difficulty": request.difficulty,
            "status": "assigned",
            "is_assignment": True,
        })
        return {
            "message": f"Exam generated for Division {target_division}",
            **response,
        }

    except HTTPException:
        raise
    except IntegrityError as exc:
        raise HTTPException(409, "An examination with this identifier already exists") from exc
    except Exception as exc:
        raise HTTPException(500, detail=f"Exam generation failed: {exc}") from exc


@app.get("/api/teacher/exams")
def list_teacher_exams(
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    with sessions_lock:
        exams = []

        for state in sessions.values():
            if not state.get("_is_assignment"):
                continue

            if state.get("_owner_email") != user["email"]:
                continue

            assignment_id = state.get("_assignment_id")
            # Read the authoritative schedule from PostgreSQL.
            with SessionLocal() as db:
               exam_record = db.get(Exam, str(assignment_id))
               scheduled_end_at = (
                 exam_record.scheduled_end_at
                 if exam_record is not None
                 else None
                )

            schedule_closed = bool(
               scheduled_end_at is not None
               and _utc(scheduled_end_at) <= datetime.now(timezone.utc)
            )

            attempts = [
                attempt
                for attempt in sessions.values()
                if attempt.get("_assignment_id") == assignment_id
                and not attempt.get("_is_assignment")
            ]

            submitted = 0
            in_progress = 0

            for attempt in attempts:
                session = attempt.get("exam_session") or {}
                status = str(session.get("status") or "")

                if status in ("submitted", "evaluated", "completed"):
                    submitted += 1
                elif status == "in_progress":
                    in_progress += 1

            exam = public_session(state)

            exam.update({
                "session_id": assignment_id,
                "assignment_id": assignment_id,
                "division": state.get("_target_division"),
                "subject": state.get("_subject"),
                "topic": state.get("_topic"),
                "difficulty": state.get("_difficulty"),
                "status": "assigned",
                "is_assignment": True,
                "attempt_count": len(attempts),
                "submitted_count": submitted,
                "in_progress_count": in_progress,
                "scheduled_end_at": scheduled_end_at,
                "schedule_closed": schedule_closed, 
            })

            exams.append(exam)

        return {"exams": exams}

@app.get("/api/student/exams")
def list_student_exams(
    user: dict[str, Any] = Depends(require_role("student")),
):
    student_division = user.get("division")

    if not student_division:
        return {"exams": []}

    with sessions_lock:
        exams = []

        for state in sessions.values():
            if not state.get("_is_assignment"):
                continue

            if not _same_division(
                state.get("_target_division"),
                student_division,
            ):
                continue

            assignment_id = state.get("_assignment_id")

            # Fetch scheduling information from PostgreSQL.
            with SessionLocal() as db:
                assignment = db.get(Exam, str(assignment_id))

                schedule_info = {
                    "scheduled_start_at": (
                        assignment.scheduled_start_at
                        if assignment else None
                    ),
                    "scheduled_end_at": (
                        assignment.scheduled_end_at
                        if assignment else None
                    ),
                    "duration_minutes": (
                        assignment.duration_minutes
                        if assignment else 30
                    ),
                }

            existing = _student_attempt_for_assignment(
                assignment_id,
                user["email"],
            )

            if existing:
                attempt_id, attempt_state = existing
                exam = public_session(attempt_state)

                exam.update({
                    "session_id": attempt_id,
                    "assignment_id": assignment_id,
                    "division": state.get("_target_division"),
                    "subject": state.get("_subject"),
                    "topic": state.get("_topic"),
                    "difficulty": state.get("_difficulty"),
                    "has_attempt": True,
                    **schedule_info,
                })

            else:
                exam = public_session(state)

                exam.update({
                    "session_id": assignment_id,
                    "assignment_id": assignment_id,
                    "division": state.get("_target_division"),
                    "subject": state.get("_subject"),
                    "topic": state.get("_topic"),
                    "difficulty": state.get("_difficulty"),
                    "status": "not_started",
                    "answered_questions": 0,
                    "has_attempt": False,
                    **schedule_info,
                })

            exams.append(exam)

        return {"exams": exams}


def _create_student_attempt(
    assignment: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    """
    Create an independent ExamSession for ONE student from the division
    assignment. Questions are reused; answers/session state are NOT shared.
    """
    assignment_id = assignment["_assignment_id"]

    existing = _student_attempt_for_assignment(
        assignment_id,
        user["email"],
    )

    if existing:
        return existing[1]

    questions = (
        assignment.get("questions")
        or assignment.get("validated_questions")
        or []
    )

    if not questions:
        raise HTTPException(
            status_code=500,
            detail="Generated examination contains no questions",
        )

    student_id = str(
        user.get("usn")
        or user.get("roll_number")
        or user["email"]
    )

    schedule = _check_start_window(assignment_id)

    # Create a completely independent session.
    new_session = session_agent.create_session(
        exam_id=str(
            (assignment.get("exam_session") or {}).get("exam_id")
            or assignment_id
        ),
        student_id=student_id,
        questions=questions,
        duration_minutes=schedule["duration_minutes"],
    )

    new_session = session_agent.start_session(new_session)

    attempt = deepcopy(assignment)

    attempt["_is_assignment"] = False
    attempt["_assignment_id"] = assignment_id
    attempt["_student_email"] = user["email"]
    attempt["_student_roll_number"] = user.get("roll_number")
    attempt["_student_usn"] = user.get("usn")
    attempt["_student_name"] = user.get("name")
    attempt["_target_division"] = user.get("division")

    attempt["exam_session"] = new_session.model_dump(mode="json")
    if schedule["scheduled_end_at"]:
        session_end = _utc(datetime.fromisoformat(
            str(attempt["exam_session"]["ends_at"]).replace("Z", "+00:00")
        ))
        deadline = min(session_end, _utc(schedule["scheduled_end_at"]))
        attempt["exam_session"]["ends_at"] = deadline.isoformat()
        # Ensure the validated session and persisted state use the same deadline.
        new_session = ExamSession.model_validate(attempt["exam_session"])
    attempt["answers"] = []
    attempt["evaluation_results"] = []
    attempt["final_result"] = None

    # Rebuild safe questions from the full generated questions.
    attempt["student_questions"] = session_agent.get_questions(
        new_session,
        questions,
    )

    with SessionLocal.begin() as db:
        db.add(ExamAttempt(
            id=str(new_session.session_id), exam_id=assignment_id,
            student_id=user["id"], status="in_progress",
            started_at=_utc(datetime.fromisoformat(
                str(attempt["exam_session"]["started_at"]).replace("Z", "+00:00")
            )),
            ends_at=_utc(datetime.fromisoformat(
                str(attempt["exam_session"]["ends_at"]).replace("Z", "+00:00")
            )),
            session_state=json.loads(json.dumps(attempt, default=str)),
        ))

    _save_state(attempt)
    sessions[new_session.session_id] = attempt

    return attempt


@app.get("/api/exams/{session_id}")
def get_exam(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    with sessions_lock:
        state = load_session(session_id)

        # Teacher may inspect their assignment.
        if user["role"] == "teacher":
            if state.get("_owner_email") != user["email"]:
                raise HTTPException(
                    status_code=403,
                    detail="You cannot access this examination",
                )

            return {
                **public_session(state),
                "division": state.get("_target_division"),
                "subject": state.get("_subject"),
                "topic": state.get("_topic"),
            }

        # Reading an assignment must NOT create a timed attempt.
        # Students start it explicitly via POST /start after consent.
        if state.get("_is_assignment"):
            if not _same_division(
                state.get("_target_division"),
                user.get("division"),
            ):
                raise HTTPException(
                    status_code=403,
                    detail="This examination is assigned to another division",
                )
            return public_session(state)

        if not _can_access_attempt(state, user):
            raise HTTPException(
                status_code=403,
                detail="This examination is not assigned to your account",
            )

        return public_session(state)


@app.post("/api/exams/{assignment_id}/start")
def start_student_exam(
    assignment_id: str,
    request: StartExamRequest,
    user: dict[str, Any] = Depends(require_role("student")),
):
    if request.consent_accepted is not True:
        raise HTTPException(403, "Camera and microphone recording consent is required")

    with sessions_lock:
        state = load_session(assignment_id)

        # Older student exam cards can contain an existing attempt ID.
        # Resolve that ID to its parent assignment, but never let one
        # student access somebody else's attempt.
        if not state.get("_is_assignment"):
            if not _can_access_attempt(state, user):
                raise HTTPException(403, "Not your examination attempt")
            assignment_id = str(state["_assignment_id"])
            state = load_session(assignment_id)

        if not _same_division(state.get("_target_division"), user.get("division")):
            raise HTTPException(403, "This examination is assigned to another division")

        # Reuse an existing valid attempt. A real exam cannot be restarted
        # or have its deadline reset by clicking Start again.
        attempt = _create_student_attempt(state, user)
        status = str((attempt.get("exam_session") or {}).get("status"))
        if status != "in_progress":
            raise HTTPException(
                409, "This examination was already completed. A new attempt is not allowed."
            )

        try:
            _check_attempt_deadline(attempt)
        except HTTPException as exc:
            raise HTTPException(
                409,
                "This existing attempt has expired. Its timer cannot be restarted."
            ) from exc

        return public_session(attempt)



# ============================================================
# CLAIM AN EXAM CLIENT
# ============================================================

@app.post("/api/exams/{session_id}/client/claim")
def claim_exam_client(
    session_id: str,
    request: ExamClientRequest,
    user: dict[str, Any] = Depends(require_role("student")),
):
    with sessions_lock:
        state = load_session(session_id)
        verify_active_student_attempt(state, user)

        now = datetime.now(timezone.utc)
        registered = state.get("_exam_client_id")
        last_seen = state.get("_exam_client_last_seen")

        recently_active = False

        if registered and last_seen:
            try:
                last_time = _utc(
                    datetime.fromisoformat(
                        str(last_seen).replace("Z", "+00:00")
                    )
                )
                recently_active = (
                    (now - last_time).total_seconds()
                    < EXAM_HEARTBEAT_TIMEOUT_SECONDS
                )
            except ValueError:
                recently_active = False

        if (
            registered
            and registered != request.client_id
            and recently_active
        ):
            raise HTTPException(
                409,
                "This examination is already active in another session.",
            )

        state["_exam_client_id"] = request.client_id
        state["_exam_client_last_seen"] = now.isoformat()

        _save_state(state)
        sessions[session_id] = state

        return {
            "message": "Exam client registered",
            "status": "in_progress",
            "heartbeat_interval_seconds": 15,
        }


# ============================================================
# EXAM HEARTBEAT
# ============================================================

@app.post("/api/exams/{session_id}/client/heartbeat")
def exam_heartbeat(
    session_id: str,
    request: ExamClientRequest,
    user: dict[str, Any] = Depends(require_role("student")),
):
    with sessions_lock:
        state = load_session(session_id)

        verify_active_student_attempt(state, user)
        verify_exam_client(state, request.client_id)

        state["_exam_client_last_seen"] = (
            datetime.now(timezone.utc).isoformat()
        )

        _save_state(state)
        sessions[session_id] = state

        return {
            "status": "in_progress",
            "connected": True,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }



# ============================================================
# PROCTORING - EVENTS AND AUTOMATIC TERMINATION
# ============================================================

@app.post("/api/exams/{session_id}/proctoring/events")
def record_proctoring_event(
    session_id: str,
    request: ProctoringEventRequest,
    user: dict[str, Any] = Depends(require_role("student")),
):
    if request.event_type not in ALLOWED_PROCTORING_EVENTS:
        raise HTTPException(
            422, "Unsupported proctoring event type"
        )

    if len(json.dumps(request.details)) > 2048:
        raise HTTPException(
            422, "Proctoring event details are too large"
        )

    with sessions_lock:

        # First save the security event and determine
        # the official incident count.
        with SessionLocal.begin() as db:

            attempt = db.get(ExamAttempt, session_id)

            if attempt is None:
                raise HTTPException(
                    404, "Exam attempt not found"
                )

            if attempt.student_id != user["id"]:
                raise HTTPException(
                    403, "This is not your exam attempt"
                )

            if attempt.status != "in_progress":
                raise HTTPException(
                    409, "This examination has already ended"
                )

            event = ProctoringEvent(
                attempt_id=attempt.id,
                event_type=request.event_type,
                details=request.details,
                occurred_at=datetime.now(timezone.utc),
            )

            db.add(event)
            db.flush()

            event_id = event.id

            attempt_events = db.scalars(
                select(ProctoringEvent)
                .where(
                    ProctoringEvent.attempt_id == attempt.id
                )
                .order_by(
                    ProctoringEvent.occurred_at,
                    ProctoringEvent.id,
                )
            ).all()

            warning_status = (
                calculate_proctoring_warning_status(
                    attempt_events
                )
            )

        # The event transaction has committed.
        # Never call the shared finalization function
        # inside the database transaction above.

        if warning_status["termination_threshold_reached"]:

            termination_result = finalize_exam_locked(
                session_id,
                proctoring_terminated=True,
            )

            return {
                "message": "Exam automatically terminated",
                "event_id": event_id,
                "attempt_id": session_id,
                "event_type": request.event_type,
                **warning_status,
                "exam_terminated": True,
                "termination_result": termination_result,
            }

        return {
            "message": "Proctoring event recorded",
            "event_id": event_id,
            "attempt_id": session_id,
            "event_type": request.event_type,
            **warning_status,
            "exam_terminated": False,
            "termination_result": None,
        }


# ============================================================
# PROCTORING - RECORD SECURITY VIOLATIONS
# ============================================================

@app.post("/api/exams/{session_id}/answers")
def save_answer(
    session_id: str,
    request: AnswerRequest,
    client_id: str | None = Header(default=None, alias="X-Exam-Client"),
    user: dict[str, Any] = Depends(require_role("student")),
):
    with sessions_lock:
        state = load_session(session_id)

        # 1. Ensure this is a student attempt.
        if state.get("_is_assignment"):
            raise HTTPException(
                status_code=409,
                detail="Start the examination before answering",
            )

        # 2. Verify that this attempt belongs to the student.
        if not _can_access_attempt(state, user):
            raise HTTPException(
                status_code=403,
                detail="This examination is not assigned to your account",
            )

        # 3. Verify that this is the registered exam browser.
        verify_exam_client(state, client_id)

        try:
            session = ExamSession.model_validate(
                state["exam_session"]
            )

            # 4. Reject answers after time expires.
            _check_attempt_deadline(state)

            # 5. Reject answers after submission or termination.
            if session.status != ExamSessionStatus.IN_PROGRESS:
                raise HTTPException(
                    status_code=409,
                    detail="This exam is not accepting answers",
                )

            # 6. Verify the question belongs to this attempt.
            if request.question_id not in session_question_ids(state):
                raise HTTPException(
                    status_code=404,
                    detail="Question not found in this examination",
                )

            # 7. Save the student's answer.
            session_agent.submit_answer(
                session=session,
                question_id=request.question_id,
                answer=request.answer,
            )

            state["exam_session"] = session.model_dump(mode="json")

            state["answers"] = [
                answer.model_dump(mode="json")
                for answer in session.answers.values()
            ]

            # 8. Persist the answer in PostgreSQL.
            _save_state(state)
            sessions[session_id] = state

            return {
                "message": "Answer saved",
                "answered_questions": session.answered_questions,
                "total_questions": session.total_questions,
            }

        except HTTPException:
            raise

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc




@app.post("/api/exams/{session_id}/submit")
def submit_exam(
    session_id: str,
    user: dict[str, Any] = Depends(require_role("student")),
):
    with sessions_lock:
        state = load_session(session_id)

        if state.get("_is_assignment"):
            raise HTTPException(
                409, "Start the examination before submitting"
            )

        if not _can_access_attempt(state, user):
            raise HTTPException(
                403, "This examination is not assigned to you"
            )

        try:
            return finalize_exam_locked(
                session_id,
                proctoring_terminated=False,
            )

        except HTTPException:
            raise

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc


@app.get("/api/exams/{session_id}/results")
def get_results(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    with sessions_lock:
        state = load_session(session_id)

        if state.get("_is_assignment"):
            raise HTTPException(
                status_code=409,
                detail="This is an examination assignment, not a student attempt",
            )

        if user["role"] == "student":
            if not _can_access_attempt(state, user):
                raise HTTPException(
                    status_code=403,
                    detail="You cannot access these results",
                )
        elif state.get("_owner_email") != user["email"]:
            raise HTTPException(
                status_code=403,
                detail="You cannot access these results",
            )

        result = state.get("final_result")

        if not result:
            raise HTTPException(
                status_code=409,
                detail="Results are available only after submission and evaluation",
            )

        return {
            "result": result,
            "evaluation_results": state.get(
                "evaluation_results",
                [],
            ),
        }

@app.get("/api/teacher/results")
def teacher_results(
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """
    Return evaluated student attempts belonging to the logged-in teacher.

    Fetches attempts directly from PostgreSQL so results generated
    by the separate timeout worker are also visible.
    """

    rows: list[dict[str, Any]] = []

    with SessionLocal() as db:

        attempts = db.scalars(
            select(ExamAttempt)
        ).all()

        for attempt in attempts:

            state = attempt.session_state or {}

            # Skip missing or invalid session states.
            if not isinstance(state, dict):
                continue

            # Skip exam assignments.
            if state.get("_is_assignment"):
                continue

            # Only show attempts belonging to this teacher.
            if state.get("_owner_email") != user["email"]:
                continue

            final_result = state.get("final_result")
            evaluation_results = (
                state.get("evaluation_results") or []
            )

            # Skip attempts that have not been evaluated.
            if not final_result and not evaluation_results:
                continue

            detail_rows = []

            if isinstance(final_result, dict):
                maybe_rows = final_result.get("results")

                if isinstance(maybe_rows, list):
                    detail_rows = maybe_rows

            if not detail_rows and isinstance(evaluation_results, list):
                detail_rows = evaluation_results

            obtained = sum(
                float(item.get("marks_awarded", 0) or 0)
                for item in detail_rows
                if isinstance(item, dict)
            )

            total = sum(
                float(item.get("total_marks", 0) or 0)
                for item in detail_rows
                if isinstance(item, dict)
            )

            percentage = (
                round((obtained / total) * 100, 2)
                if total else 0
            )

            session_data = state.get("exam_session") or {}
            
            
            # ----------------------------------------------
            # PROCTORING SUMMARY FOR THIS STUDENT ATTEMPT
            # ----------------------------------------------

            proctoring_events = db.scalars(
                select(ProctoringEvent)
                .where(
                    ProctoringEvent.attempt_id == attempt.id
                )
                .order_by(
                    ProctoringEvent.occurred_at,
                    ProctoringEvent.id,
                )
            ).all()

            proctoring_status = (
                calculate_proctoring_warning_status(
                    proctoring_events
                )
            )

            
            proctoring_details = [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "message": (
                        (event.details or {}).get("message")
                        or event.event_type
                    ),
                   "details": event.details or {},
                   "occurred_at": event.occurred_at.isoformat(),
                }
                for event in proctoring_events
            ]


            rows.append({
                "session_id": attempt.id,
                "started_at": (
                    session_data.get("started_at")
                    or (
                        attempt.started_at.isoformat()
                        if attempt.started_at
                        else None
                    )
                ),
                "warning_count": min(
    proctoring_status["incident_count"], 3
),
"incident_count": proctoring_status["incident_count"],
"security_event_count": proctoring_status["total_events"],
"proctoring_terminated": bool(
    state.get("_proctoring_terminated", False)
),
"proctoring_events": proctoring_details,
                "assignment_id": state.get("_assignment_id"),
                "student_name": state.get("_student_name") or "Student",
                "student_usn": state.get("_student_usn") or "",
                "student_roll_number": (
                    state.get("_student_roll_number") or ""
                ),
                "division": state.get("_target_division") or "",
                "subject": state.get("_subject") or "",
                "topic": state.get("_topic") or "",
                "marks": obtained,
                "total_marks": total,
                "percentage": percentage,
                "status": (
                    final_result.get("status", "completed")
                    if isinstance(final_result, dict)
                    else session_data.get(
                        "status",
                        attempt.status or "completed",
                    )
                ),
            })

    return {"results": rows}


# ---------------------------------------------------------------------------
# Professor notes management (SQLite; teacher identity comes from PostgreSQL)
# ---------------------------------------------------------------------------

def validate_note_file_header(
    extension: str,
    content: bytes,
) -> None:
    """
    Validate file signature against its extension.
    """

    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=415,
                detail="Invalid PDF file.",
            )

    elif extension in {".docx", ".pptx"}:
        if not content.startswith(b"PK"):
            raise HTTPException(
                status_code=415,
                detail=f"Invalid {extension[1:].upper()} file.",
            )

    elif extension == ".txt":
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=415,
                detail="TXT files must use UTF-8 encoding.",
            )


# ============================================================
# 1. UPLOAD PROFESSOR NOTES
# ============================================================


@app.post("/api/teacher/notes", status_code=201)
async def upload_teacher_note(
    file: UploadFile = File(...),
    subject: str = Form(..., min_length=1, max_length=80),
    topic: str | None = Form(default=None, max_length=120),
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """
    Upload professor notes, extract their text,
    and save the extracted content in SQLite.
    """

    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if not original_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename.",
        )

    if extension not in ALLOWED_NOTE_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file format. Allowed: PDF, DOCX, PPTX, TXT.",
        )

    document_id = str(uuid4())
    stored_filename = f"{document_id}{extension}"

    teacher_dir = NOTES_STORAGE_DIR / str(user["id"])
    teacher_dir.mkdir(parents=True, exist_ok=True)

    destination = teacher_dir / stored_filename
    temp_destination = teacher_dir / f".{stored_filename}.uploading"

    total_size = 0
    header = b""

    try:
        # -----------------------------------------
        # 1. SAVE UPLOADED FILE
        # -----------------------------------------

        with temp_destination.open("wb") as output:

            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_NOTE_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 25 MB limit.",
                    )

                if len(header) < 16:
                    header += chunk[:16 - len(header)]

                output.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        validate_note_file_header(extension, header)

        temp_destination.replace(destination)

        # -----------------------------------------
        # 2. EXTRACT DOCUMENT TEXT
        # -----------------------------------------

        extracted_text = None
        processing_status = "processed"
        extraction_error = None
        saved_chunks = 0

        try:
            extracted_text = extract_text(destination)

            if not extracted_text.strip():
                raise DocumentExtractionError(
                    "No readable text found in the document."
                )

            # -----------------------------------------
            # CHUNK DOCUMENT AND GENERATE EMBEDDINGS
            # -----------------------------------------

            chunks = chunk_text(
                extracted_text,
                chunk_size=180,
                overlap=30,
            )

            if not chunks:
                raise DocumentExtractionError(
                    "No valid text chunks could be generated."
                )

            saved_chunks = save_chunks(
                document_id=document_id,
                teacher_id=user["id"],
                subject=subject.strip(),
                topic=(
                    topic.strip()
                    if topic and topic.strip()
                    else None
                ),
                chunks=chunks,
            )

        except DocumentExtractionError as error:
            processing_status = "failed"
            extraction_error = str(error)
        except Exception as error:
            processing_status = "failed"
            extraction_error = str(error)

        # -----------------------------------------
        # 3. SAVE FILE METADATA AND EXTRACTED TEXT
        # -----------------------------------------

        with sqlite3.connect(NOTES_DB) as db:

            db.execute(
                """
                INSERT INTO teacher_notes (
                    document_id,
                    teacher_id,
                    original_filename,
                    stored_filename,
                    file_extension,
                    content_type,
                    file_size,
                    subject,
                    topic,
                    storage_path,
                    processing_status,
                    extracted_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    user["id"],
                    original_name,
                    stored_filename,
                    extension,
                    file.content_type,
                    total_size,
                    subject.strip(),
                    topic.strip() if topic and topic.strip() else None,
                    str(destination),
                    processing_status,
                    extracted_text,
                ),
            )

            db.commit()

        # -----------------------------------------
        # 4. RETURN RESPONSE
        # -----------------------------------------

        response = {
            "document_id": document_id,
            "filename": original_name,
            "file_type": extension.lstrip("."),
            "file_size": total_size,
            "subject": subject.strip(),
            "topic": topic.strip() if topic and topic.strip() else None,
            "processing_status": processing_status,
            "extracted_characters": len(extracted_text) if extracted_text else 0,
            "total_chunks": saved_chunks if processing_status == "processed" else 0,
        }

        if extraction_error:
            response["extraction_error"] = extraction_error

        return {
            "message": (
                "Notes uploaded and processed successfully."
                if processing_status == "processed"
                else "Notes uploaded, but text extraction failed."
            ),
            "document": response,
        }

    except Exception:
        temp_destination.unlink(missing_ok=True)

        # Preserve the file if its metadata was already saved.
        with sqlite3.connect(NOTES_DB) as db:
            saved = db.execute(
                """
                SELECT 1 FROM teacher_notes
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

        if not saved:
            destination.unlink(missing_ok=True)

        raise

    finally:
        await file.close()


# ============================================================
# 2. LIST PROFESSOR NOTES
# ============================================================


@app.get("/api/teacher/notes")
def list_teacher_notes(
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """
    Return only the authenticated teacher's uploaded notes.
    """

    with sqlite3.connect(NOTES_DB) as db:
        db.row_factory = sqlite3.Row

        rows = db.execute(
            """
            SELECT
                document_id,
                original_filename,
                file_extension,
                file_size,
                subject,
                topic,
                processing_status,
                created_at
            FROM teacher_notes
            WHERE teacher_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    documents = [
        {
            "document_id": row["document_id"],
            "filename": row["original_filename"],
            "file_type": row["file_extension"].lstrip("."),
            "file_size": row["file_size"],
            "subject": row["subject"],
            "topic": row["topic"],
            "processing_status": row["processing_status"],
            "uploaded_at": row["created_at"],
        }
        for row in rows
    ]

    return {"documents": documents}


# ============================================================
# 3. DELETE PROFESSOR NOTES
# ============================================================


@app.delete("/api/teacher/notes/{document_id}")
def delete_teacher_note(
    document_id: str,
    user: dict[str, Any] = Depends(require_role("teacher")),
):
    """
    Delete a document only if it belongs to the authenticated teacher.
    """

    with sqlite3.connect(NOTES_DB) as db:
        db.row_factory = sqlite3.Row

        row = db.execute(
            """
            SELECT storage_path
            FROM teacher_notes
            WHERE document_id = ?
            AND teacher_id = ?
            """,
            (document_id, user["id"]),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Notes document not found.",
            )

        db.execute(
            """
            DELETE FROM teacher_notes
            WHERE document_id = ?
            AND teacher_id = ?
            """,
            (document_id, user["id"]),
        )
        db.commit()

    Path(row["storage_path"]).unlink(missing_ok=True)

    return {
        "message": "Notes deleted successfully.",
        "document_id": document_id,
    }