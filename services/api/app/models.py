from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TaskSpec(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="zh-CN", max_length=20)
    questions: list[str] = Field(default_factory=list, max_length=20)
    required_slots: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("goal must not be blank")
        return value


class CreateCall(BaseModel):
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    task: TaskSpec
    mode: Literal["mock", "real"] = "mock"
    confirmed: bool = False


class CreateCallResponse(BaseModel):
    call_id: str
    status: str
    mode: str
    status_url: str

