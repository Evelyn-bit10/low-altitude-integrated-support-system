"""Stateless task draft completeness checks, without operational decisions."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter()


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    task_id: str | None = Field(default=None, max_length=100)
    aircraft_id: str | None = Field(default=None, max_length=100)
    operation: Literal["arrival", "departure"] | None = None
    site_id: str | None = Field(default=None, max_length=100)
    payload_description: str | None = Field(default=None, max_length=500)
    payload_weight_kg: float | None = Field(default=None, ge=0, le=100000)

    @field_validator("task_id", "aircraft_id", "site_id", "payload_description", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value


@router.post("/task-drafts/check")
def check_task_draft(draft: TaskDraft):
    labels = {
        "task_id": "任务编号", "aircraft_id": "航空器标识", "operation": "进场或离场",
        "site_id": "起降点标识", "payload_description": "载荷说明", "payload_weight_kg": "载荷重量",
    }
    values = draft.model_dump()
    missing = [{"field": field, "label": label} for field, label in labels.items() if values[field] is None]
    return {
        "draft": values,
        "missing_information": missing,
        "draft_complete": not missing,
        "operationally_validated": False,
        "executed": False,
        "notice": "仅检查草稿字段是否填写，不验证真实性、适航性或运行许可，不执行任务。",
    }
