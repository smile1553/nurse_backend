from datetime import datetime
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


class StudentResultSubmission(ApiModel):
    studentId: str = Field(min_length=1, max_length=64)
    loginTime: datetime
    correctCount: int = Field(strict=True, ge=0, le=8)
    toneScore: int = Field(strict=True, ge=0, le=20)

    @field_validator("loginTime")
    @classmethod
    def login_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("loginTime must include a timezone offset")
        return value


def isoformat_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
