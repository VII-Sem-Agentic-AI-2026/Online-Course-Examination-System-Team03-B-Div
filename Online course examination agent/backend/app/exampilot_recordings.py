"""Private recording chunk storage for ExamPilot.

Stage 1: authenticated chunk upload and teacher-only download.
Never mount RECORDING_ROOT as StaticFiles.
"""
from __future__ import annotations
import shutil
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models import Exam, ExamAttempt

RECORDING_ROOT = Path(
    os.environ.get(
        "EXAMPILOT_RECORDING_DIR",
        str(Path(__file__).resolve().parent / "private_recordings"),
    )
).resolve()
MAX_CHUNK_BYTES = 5 * 1024 * 1024
MAX_CHUNKS_PER_ATTEMPT = 10_000
GRACE_PERIOD = timedelta(minutes=2)


def _attempt_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "Invalid attempt ID") from exc


def _get_attempt(db: Session, attempt_id: str) -> ExamAttempt:
    attempt = db.get(ExamAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Exam attempt not found")
    return attempt


def _teacher_allowed(db: Session, attempt: ExamAttempt, user: dict[str, Any]) -> None:
    if user.get("role") != "teacher":
        raise HTTPException(403, "Teacher access required")
    exam = db.get(Exam, attempt.exam_id)
    if exam is None or exam.teacher_id != int(user["id"]):
        raise HTTPException(403, "Not authorized for this exam")


def _student_allowed(
    attempt: ExamAttempt,
    user: dict[str, Any],
    client_id: str | None,
) -> None:
    if user.get("role") != "student" or attempt.student_id != int(user["id"]):
        raise HTTPException(403, "Not authorized for this attempt")

    state = attempt.session_state or {}
    expected = state.get("_exam_client_id")
    if expected and client_id != expected:
        raise HTTPException(409, "This is not the registered exam client")

    # Allow a short upload grace period after submission for the final chunk.
    if attempt.status == "in_progress":
        return
    end = attempt.submitted_at or attempt.evaluated_at
    if (
        attempt.status in {"submitted", "expired", "evaluated", "completed"}
        and end is not None
        and (datetime.now(timezone.utc) - (
            end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        )) <= GRACE_PERIOD
    ):
        return
    raise HTTPException(409, "Recording uploads are closed for this attempt")


def create_recordings_router(auth_dependency: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/exams/{session_id}/recordings/chunks")
    async def upload_chunk(
        session_id: str,
        sequence: int = Form(..., ge=0, lt=MAX_CHUNKS_PER_ATTEMPT),
        chunk: UploadFile = File(...),
        x_exam_client: str | None = Header(None, alias="X-Exam-Client"),
        user: dict[str, Any] = Depends(auth_dependency),
    ):
        attempt_id = _attempt_id(session_id)
        content_type = (chunk.content_type or "").split(";", 1)[0].lower()
        extensions = {"video/webm": "webm", "video/mp4": "mp4"}
        if content_type not in extensions:
            raise HTTPException(415, "Recording must be WebM or MP4")

        with SessionLocal() as db:
            attempt = _get_attempt(db, attempt_id)
            _student_allowed(attempt, user, x_exam_client)

        directory = RECORDING_ROOT / attempt_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"chunk_{sequence:06d}.{extensions[content_type]}"

        if destination.exists():
            return {"sequence": sequence, "stored": True, "duplicate": True}

        # Exclusive creation prevents replacing an earlier recording chunk.
        try:
            with destination.open("xb") as output:
                size = 0
                while data := await chunk.read(64 * 1024):
                    size += len(data)
                    if size > MAX_CHUNK_BYTES:
                        raise HTTPException(413, "Recording chunk exceeds 5 MB")
                    output.write(data)
            if size == 0:
                raise HTTPException(400, "Recording chunk was empty")
        except FileExistsError:
            return {"sequence": sequence, "stored": True, "duplicate": True}
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await chunk.close()

        return {"sequence": sequence, "stored": True, "bytes": size}

    @router.get("/teacher/exams/{session_id}/recordings")
    def list_chunks(
        session_id: str,
        user: dict[str, Any] = Depends(auth_dependency),
    ):
        attempt_id = _attempt_id(session_id)
        with SessionLocal() as db:
            attempt = _get_attempt(db, attempt_id)
            _teacher_allowed(db, attempt, user)

        directory = RECORDING_ROOT / attempt_id
        chunks = []
        if directory.is_dir():
            for file in sorted(directory.glob("chunk_*")):
                if file.suffix not in {".webm", ".mp4"}:
                    continue
                chunks.append({
                    "filename": file.name,
                    "bytes": file.stat().st_size,
                    "sequence": int(file.stem.removeprefix("chunk_")),
                })
        return {"session_id": attempt_id, "chunks": chunks}

    @router.get("/teacher/exams/{session_id}/recordings/{sequence}")
    def download_chunk(
        session_id: str,
        sequence: int,
        user: dict[str, Any] = Depends(auth_dependency),
    ):
        attempt_id = _attempt_id(session_id)
        if sequence < 0 or sequence >= MAX_CHUNKS_PER_ATTEMPT:
            raise HTTPException(404, "Recording chunk not found")
        with SessionLocal() as db:
            attempt = _get_attempt(db, attempt_id)
            _teacher_allowed(db, attempt, user)

        directory = RECORDING_ROOT / attempt_id
        for ext, mime in (("webm", "video/webm"), ("mp4", "video/mp4")):
            file = directory / f"chunk_{sequence:06d}.{ext}"
            if file.is_file():
                return FileResponse(file, media_type=mime, filename=file.name)
        raise HTTPException(404, "Recording chunk not found")
    
    
    
    @router.get(
        "/teacher/exams/{session_id}/recording-video"
    )
    def get_complete_recording(
        session_id: str,
        user: dict[str, Any] = Depends(auth_dependency),
    ):
        attempt_id = _attempt_id(session_id)

        # Only the teacher who owns the exam may view it.
        with SessionLocal() as db:
            attempt = _get_attempt(db, attempt_id)
            _teacher_allowed(db, attempt, user)

        directory = RECORDING_ROOT / attempt_id

        if not directory.is_dir():
            raise HTTPException(
                404, "No recording found for this attempt"
            )

        chunks = sorted(
            [
                p for p in directory.iterdir()
                if p.is_file()
                and p.name.startswith("chunk_")
                and p.suffix in {".webm", ".mp4"}
                and p.stem[6:].isdigit()
            ],
            key=lambda p: int(p.stem[6:]),
        )

        if not chunks:
            raise HTTPException(
                404, "No recording chunks found"
            )

        # All chunks must belong to one recording format.
        extension = chunks[0].suffix

        if any(p.suffix != extension for p in chunks):
            raise HTTPException(
                409, "Recording contains mixed formats"
            )

        sequences = [
            int(p.stem[6:]) for p in chunks
        ]

        if sequences != list(range(len(chunks))):
            raise HTTPException(
                409, "Recording has missing chunks"
            )

        combined = directory / (
            f"complete_recording{extension}"
        )

        # Rebuild if new chunks have arrived.
        newest_chunk_time = max(
            p.stat().st_mtime_ns for p in chunks
        )

        needs_rebuild = (
            not combined.exists()
            or combined.stat().st_mtime_ns
               < newest_chunk_time
        )

        if needs_rebuild:
            # Build to a temporary path, then atomically
            # replace the complete recording.
            import tempfile

            temp_path = None

            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=directory,
                    suffix=".tmp",
                    delete=False,
                ) as output:
                    temp_path = output.name

                    for part in chunks:
                        with part.open("rb") as source:
                            shutil.copyfileobj(
                                source, output
                            )

                os.replace(temp_path, combined)

            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

        mime = (
            "video/mp4"
            if extension == ".mp4"
            else "video/webm"
        )

        return FileResponse(
            path=combined,
            media_type=mime,
            filename=combined.name,
        )


    return router
