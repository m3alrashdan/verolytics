"""Pydantic models for the generated report."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


def _as_str(v: Any) -> Any:
    """Coerce numbers/bools to str. Models often emit KPI values as floats."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return v


class KPI(BaseModel):
    label: str
    value: str            # display value, must be traceable to results
    change: str | None = None      # period-over-period change, e.g. "+12.4%"
    change_direction: str | None = None  # up | down | flat

    @field_validator("label", "value", "change", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> Any:
        return _as_str(v)


class ChartMeta(BaseModel):
    name: str
    title: str
    html_path: str
    json_path: str | None = None
    png_path: str | None = None


class AnomalyInsight(BaseModel):
    title: str
    narrative: str        # investigation narrative — numbers verified like all text
    tag: str = "one_time_event"  # one_time_event | emerging_trend | seasonal_pattern | data_error
    chart_name: str | None = None


class Segment(BaseModel):
    name: str             # LLM-generated human-readable label
    description: str
    recommendation: str


class Finding(BaseModel):
    title: str
    narrative: str        # interpretation text — every number must be verified
    chart_name: str | None = None   # references a ChartArtifact by name
    code: str | None = None         # the code that produced this finding


class CleaningLogEntry(BaseModel):
    action: str
    column: str | None = None
    before_count: int | None = None
    after_count: int | None = None
    justification: str


class ForecastSection(BaseModel):
    narrative: str
    model_name: str | None = None   # "Holt-Winters" | "Prophet"
    mape: float | None = None
    chart_name: str | None = None
    reliability_statement: str


class Report(BaseModel):
    session_id: str
    language: str = "en"
    title: str
    executive_summary: str
    kpis: list[KPI] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    cleaning_log: list[CleaningLogEntry] = Field(default_factory=list)
    data_quality_notes: str | None = None
    forecast: ForecastSection | None = None
    anomalies: list[AnomalyInsight] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    charts: list[ChartMeta] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recommendations", mode="before")
    @classmethod
    def _coerce_recs(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        out: list[str] = []
        for item in v:
            if isinstance(item, dict):
                item = item.get("text") or item.get("recommendation") or next(
                    (str(x) for x in item.values() if x), "")
            out.append(_as_str(item))
        return out
