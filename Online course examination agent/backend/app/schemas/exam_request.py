from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from backend.app.schemas.student import Student


class QuestionMix(BaseModel):
    normal_mcq: int = Field(default=0, ge=0)
    scenario_mcq: int = Field(default=0, ge=0)
    coding: int = Field(default=0, ge=0)


class ExamRequest(BaseModel):

    student: Student

    subject: str = Field(..., min_length=1)
    topic: Optional[str] = None
    difficulty: Optional[str] = None

    number_of_questions: int = Field(..., ge=1)

    question_mix: Optional[QuestionMix] = None

    exam_mode: str = "practice"

    # Selected professor notes
    document_ids: list[str] = Field(default_factory=list)

    # Exam scheduling
    duration_minutes: int = Field(default=30, ge=1, le=480)

    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if (
            self.scheduled_start_at
            and self.scheduled_end_at
            and self.scheduled_end_at <= self.scheduled_start_at
        ):
            raise ValueError(
                "Scheduled end time must be after scheduled start time."
            )

        return self