from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RouteSource = Literal["knowledge", "realtime_tool", "hybrid"]
ExecutionMode = Literal["direct_answer", "direct_tool", "rag_then_tool", "planner"]


class RouteDecision(BaseModel):
    """统一描述一次请求的数据来源、知识范围和执行模式。"""

    source: RouteSource = "knowledge"
    execution_mode: ExecutionMode = "direct_answer"
    document_types: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
