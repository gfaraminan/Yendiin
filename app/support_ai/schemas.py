from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SupportAIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    tenant_id: str | None = None
    user_role_hint: Literal["buyer", "producer", "support"] | None = None
    context: dict[str, Any] | None = None

    @field_validator("message")
    @classmethod
    def _sanitize_message(cls, value: str) -> str:
        sanitized = (value or "").strip()
        if not sanitized:
            raise ValueError("message no puede estar vacío")
        if len(sanitized) > 4000:
            raise ValueError("message demasiado largo")
        return sanitized

    @field_validator("context")
    @classmethod
    def _validate_context_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded) > 8000:
            raise ValueError("context demasiado grande")
        return value


class SupportAIChatResponse(BaseModel):
    answer: str
    trace_id: str
    used_tools: list[str] = Field(default_factory=list)
    citations: list[Any] | None = None
