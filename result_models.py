from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StudentRunStart(ApiModel):
    sessionId: str = Field(min_length=1, max_length=80)
    resultId: UUID
    studentId: str = Field(min_length=1, max_length=64)
    loginTime: datetime

    @field_validator("loginTime")
    @classmethod
    def login_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("loginTime must include a timezone offset")
        return value


def clean_result_items(raw: Any) -> List[dict]:
    """Per-question details for the feedback report, made safe.

    Whatever Unity sends here must never make the result itself be refused, so nothing is
    validated: entries that do not look right are simply left out.
    """
    cleaned: List[dict] = []
    if not isinstance(raw, list):
        return cleaned
    for entry in raw[:40]:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("id") or "").strip()[:64]
        if not item_id:
            continue
        try:
            wrong = max(0, min(999, int(entry.get("wrongAttempts") or 0)))
            points = max(0, min(80, int(entry.get("points") or 0)))
        except (TypeError, ValueError):
            continue
        cleaned.append({
            "id": item_id,
            "isQuiz": bool(entry.get("isQuiz", True)),
            "wrongAttempts": wrong,
            "solved": bool(entry.get("solved", False)),
            "points": points,
        })
    return cleaned


def clean_result_steps(raw: Any) -> List[dict]:
    """How long each part of the story took ([{id, seconds}]), made safe like the items."""
    cleaned: List[dict] = []
    if not isinstance(raw, list):
        return cleaned
    for entry in raw[:60]:
        if not isinstance(entry, dict):
            continue
        step_id = str(entry.get("id") or "").strip()[:64]
        try:
            seconds = float(entry.get("seconds") or 0)
        except (TypeError, ValueError):
            continue
        if not step_id or not (0 <= seconds <= 86400):
            continue
        cleaned.append({"id": step_id, "seconds": round(seconds, 1)})
    return cleaned


class StudentResultSubmission(ApiModel):
    studentId: str = Field(min_length=1, max_length=64)
    loginTime: datetime
    correctCount: int = Field(strict=True, ge=0, le=8)
    toneScore: int = Field(strict=True, ge=0, le=20)
    # Optional detailed question score (0-80) worked out by Unity: quizzes with points
    # taken off for every wrong answer, plus the hands-on tasks (choosing the cuff, choosing
    # where its arrow goes). When it is left out, QuestionScore = correctCount * 10 as before.
    questionScore: Optional[int] = Field(default=None, strict=True, ge=0, le=80)
    # Optional per-question details, only used for the feedback report (never for the score).
    # Deliberately not validated (see clean_result_items).
    items: Optional[Any] = None
    # Optional time spent in each part of the story, for the report (not validated either).
    steps: Optional[Any] = None

    @field_validator("loginTime")
    @classmethod
    def login_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("loginTime must include a timezone offset")
        return value


def isoformat_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
