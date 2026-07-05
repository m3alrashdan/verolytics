"""Pydantic models for sessions, profiling and sandbox execution results."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_plan_text(item: Any) -> str:
    """Normalise a plan entry to a string.

    Smaller / OpenAI-compatible models often return plan items as objects
    (e.g. {"description": ..., "justification": ...}) instead of plain strings.
    Flatten those to a readable sentence rather than failing validation.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        parts = [str(item[k]) for k in ("action", "description", "step", "text", "justification")
                 if item.get(k)]
        return " — ".join(dict.fromkeys(parts)) if parts else json_compact(item)
    return str(item)


def json_compact(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


class SessionStatus(str, Enum):
    UPLOADED = "uploaded"
    PLANNING = "planning"
    CLEANING = "cleaning"
    ANALYZING = "analyzing"
    INTERPRETING = "interpreting"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    semantic_type: str  # numeric | datetime | categorical | text | boolean | id
    missing_count: int
    missing_pct: float
    n_unique: int
    sample_values: list[Any] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)  # min/max/mean/std for numeric
    outlier_count_iqr: int | None = None


class DataProfile(BaseModel):
    filename: str
    file_size_bytes: int
    encoding: str | None = None
    n_rows: int
    n_cols: int
    duplicate_rows: int
    columns: list[ColumnProfile]
    candidate_time_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extra_sheets: list[str] = Field(default_factory=list)


class ChartArtifact(BaseModel):
    name: str
    title: str
    html_path: str
    json_path: str | None = None
    png_path: str | None = None


class ExecutionResult(BaseModel):
    ok: bool
    error: str | None = None
    traceback: str | None = None
    stdout: str = ""
    stderr: str = ""
    tables: dict[str, Any] = Field(default_factory=dict)
    scalars: dict[str, Any] = Field(default_factory=dict)
    charts: list[ChartArtifact] = Field(default_factory=list)
    duration_s: float = 0.0


class PlanStep(BaseModel):
    step_number: int = 0
    description: str = ""
    rationale: str = ""
    # v3: the question/expected pattern this step tests (hypothesis-driven planning).
    hypothesis: str = ""

    @field_validator("description", "rationale", "hypothesis", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> str:
        return "" if v is None else _coerce_plan_text(v)


class AnalysisPlan(BaseModel):
    cleaning_plan: list[str] = Field(default_factory=list)
    analysis_steps: list[PlanStep] = Field(default_factory=list)

    @field_validator("cleaning_plan", mode="before")
    @classmethod
    def _coerce_cleaning(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        return [_coerce_plan_text(item) for item in v]

    @field_validator("analysis_steps", mode="before")
    @classmethod
    def _coerce_steps(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, dict):
            v = [v]
        out: list[Any] = []
        for i, item in enumerate(v, start=1):
            # a bare string step → wrap it; ensure step_number is always present
            if isinstance(item, str):
                out.append({"step_number": i, "description": item, "rationale": ""})
            elif isinstance(item, dict):
                item.setdefault("step_number", i)
                out.append(item)
            else:
                out.append(item)
        return out


class StepResult(BaseModel):
    step: PlanStep
    status: str  # done | skipped
    attempts: int = 1
    code: str | None = None
    result: ExecutionResult | None = None
    skip_reason: str | None = None


class SessionState(BaseModel):
    """Full state of an analysis session as stored in the DB (JSON column)."""

    session_id: str
    filename: str
    language: str = "en"
    goal: str | None = None
    status: SessionStatus = SessionStatus.UPLOADED
    progress: float = 0.0
    progress_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    profile: DataProfile | None = None
    plan: AnalysisPlan | None = None
    cleaning_log: list[dict[str, Any]] = Field(default_factory=list)
    step_results: list[StepResult] = Field(default_factory=list)
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
