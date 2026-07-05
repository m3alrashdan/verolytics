"""Agent loop tests with a scripted fake LLM and fake sandbox (no API key, no Docker)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from api.config import Settings
from api.models.session import (
    ColumnProfile, DataProfile, ExecutionResult, SessionState,
)
from api.services.agent import AnalystAgent


# ---------------------------------------------------------------- fakes ----

class FakeBlock(SimpleNamespace):
    pass


def text_response(text: str):
    return SimpleNamespace(content=[FakeBlock(type="text", text=text)], stop_reason="end_turn")


def tool_response(code: str, tool_id: str = "tu_1"):
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", id=tool_id, name="execute_python",
                           input={"code": code})],
        stop_reason="tool_use",
    )


class FakeLLM:
    """Returns queued responses; records every call."""

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        item = self.responses.pop(0)
        return item(kwargs) if callable(item) else item

    text_of = staticmethod(lambda r: "".join(b.text for b in r.content if b.type == "text"))

    @staticmethod
    def tool_use_of(r):
        return next((b for b in r.content if b.type == "tool_use"), None)

    from api.services.llm import LLMClient as _L
    parse_json = staticmethod(_L.parse_json)


class FakeSandbox:
    """Returns queued ExecutionResults; records executed code."""

    def __init__(self, results: list[ExecutionResult]):
        self.results = list(results)
        self.executed: list[str] = []

    def execute(self, session_id: str, code: str, timeout_s: int | None = None):
        self.executed.append(code)
        return self.results.pop(0)

    def workspace(self, session_id):  # pragma: no cover - unused in tests
        raise NotImplementedError

    def ensure_image(self):
        return None


# ------------------------------------------------------------- fixtures ----

def make_state() -> SessionState:
    profile = DataProfile(
        filename="sales.csv", file_size_bytes=100, n_rows=10, n_cols=2,
        duplicate_rows=0,
        columns=[ColumnProfile(name="amount", dtype="float64", semantic_type="numeric",
                               missing_count=0, missing_pct=0.0, n_unique=10)],
    )
    return SessionState(session_id="s1", filename="sales.csv", profile=profile)


PLAN_JSON = json.dumps({
    "cleaning_plan": ["remove duplicates"],
    "analysis_steps": [
        {"step_number": 1, "description": "compute KPIs", "rationale": "overview"},
    ],
})

CLEAN_OK = ExecutionResult(ok=True, scalars={
    "cleaning_log": [{"action": "drop_duplicates", "column": None,
                      "before_count": 12, "after_count": 10, "justification": "exact dupes"}],
    "cleaned_shape": {"rows": 10, "cols": 2},
})
STEP_OK = ExecutionResult(ok=True, scalars={"total": 4200.5, "growth": 0.12})
STEP_FAIL = ExecutionResult(ok=False, error="KeyError: 'x'", traceback="Traceback ... KeyError")

GOOD_REPORT = json.dumps({
    "title": "Sales report",
    "executive_summary": "Total amount reached 4200.5, growing 12% period over period.",
    "kpis": [{"label": "Total", "value": "4200.5", "change": "+12%", "change_direction": "up"}],
    "findings": [{"title": "Total", "narrative": "The total is 4200.5.", "chart_name": None}],
    "data_quality_notes": "Removed duplicate rows.",
    "forecast": None,
    "recommendations": ["Keep monitoring the total of 4200.5."],
})

BAD_REPORT = GOOD_REPORT.replace("4200.5", "9999.9")


def settings(**overrides) -> Settings:
    # _env_file=None: tests must not inherit the developer's .env overrides.
    # Anomaly investigation is opt-in per test (it adds an LLM roundtrip).
    defaults = dict(anthropic_api_key="test", max_step_retries=3,
                    max_verification_attempts=3, enable_anomaly_investigation=False)
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def build_agent(llm_responses, sandbox_results, **setting_overrides):
    llm = FakeLLM(llm_responses)
    sandbox = FakeSandbox(sandbox_results)
    agent = AnalystAgent(llm=llm, sandbox=sandbox, settings=settings(**setting_overrides))
    return agent, llm, sandbox


# ---------------------------------------------------------------- tests ----

def test_happy_path_produces_verified_report():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),            # plan
         tool_response("clean code"),          # cleaning
         tool_response("step 1 code"),         # analysis step
         text_response(GOOD_REPORT)],          # interpretation
        [CLEAN_OK, STEP_OK],
    )
    state, report = agent.run(make_state())
    assert state.status.value == "done"
    assert [sr.status for sr in state.step_results] == ["done", "done"]
    assert state.cleaning_log[0]["action"] == "drop_duplicates"
    assert report.verification["ok"] is True
    assert report.verification["redacted"] is False
    assert report.kpis[0].value == "4200.5"


def test_retry_then_success_counts_attempts():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("bad step code"),       # attempt 1 -> fails
         tool_response("fixed step code"),     # attempt 2 -> ok
         text_response(GOOD_REPORT)],
        [CLEAN_OK, STEP_FAIL, STEP_OK],
    )
    state, report = agent.run(make_state())
    step = state.step_results[1]
    assert step.status == "done"
    assert step.attempts == 2


def test_step_skipped_after_max_retries():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("bad 1"), tool_response("bad 2"), tool_response("bad 3"),
         text_response(json.dumps({
             "title": "r", "executive_summary": "No figures available.",
             "kpis": [], "findings": [], "data_quality_notes": None,
             "forecast": None, "recommendations": []}))],
        [CLEAN_OK, STEP_FAIL, STEP_FAIL, STEP_FAIL],
    )
    state, report = agent.run(make_state())
    step = state.step_results[1]
    assert step.status == "skipped"
    assert step.attempts == 3
    assert "KeyError" in step.skip_reason


def test_verification_failure_triggers_regeneration():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("step code"),
         text_response(BAD_REPORT),            # contains 9999.9 -> rejected
         text_response(GOOD_REPORT)],          # regenerated cleanly
        [CLEAN_OK, STEP_OK],
    )
    state, report = agent.run(make_state())
    assert report.verification["ok"] is True
    # the regeneration request must mention the offending number
    regen_call = llm.calls[-1]
    assert "9999.9" in json.dumps(regen_call["messages"][-1]["content"])


def test_persistent_verification_failure_redacts():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("step code"),
         text_response(BAD_REPORT), text_response(BAD_REPORT), text_response(BAD_REPORT)],
        [CLEAN_OK, STEP_OK],
    )
    state, report = agent.run(make_state())
    assert report.verification["redacted"] is True
    # the hallucinated number must not survive in any reader-facing text
    # (verification metadata may still list it as an unmatched token)
    narrative = " ".join([report.executive_summary,
                          *(k.value for k in report.kpis),
                          *(f.narrative for f in report.findings),
                          *report.recommendations])
    assert "9999.9" not in narrative
    assert "[unverified]" in narrative


def test_step_cap_enforced():
    many_steps = json.dumps({
        "cleaning_plan": ["none"],
        "analysis_steps": [
            {"step_number": i, "description": f"s{i}", "rationale": "r"} for i in range(1, 21)
        ],
    })
    responses = [text_response(many_steps), tool_response("clean")]
    results = [CLEAN_OK]
    for _ in range(12):  # max_analysis_steps
        responses.append(tool_response("step"))
        results.append(STEP_OK)
    responses.append(text_response(GOOD_REPORT))
    agent, llm, sandbox = build_agent(responses, results)
    state, _ = agent.run(make_state())
    assert len(state.plan.analysis_steps) == 12
    assert len(state.step_results) == 13  # cleaning + 12


def test_anomaly_investigation_phase():
    """When enabled: candidates are detected, investigated via the sandbox, and
    the resulting narrative lands in the report (verified like everything else)."""
    inv_result = ExecutionResult(ok=True, scalars={"spike_total": 45000.0, "spike_share_pct": 92.0})
    report_with_anomaly = json.dumps({
        "title": "r", "executive_summary": "Total reached 4200.5.",
        "kpis": [], "findings": [], "data_quality_notes": None, "forecast": None,
        "anomalies": [{"title": "March spike", "tag": "one_time_event",
                       "narrative": "A spike of 45000.0 explains 92.0% of the jump."}],
        "segments": [], "recommendations": []})
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("step code"),
         text_response(json.dumps([{"title": "March spike", "context": "total jumped"}])),
         tool_response("drill-down code"),
         text_response(report_with_anomaly)],
        [CLEAN_OK, STEP_OK, inv_result],
        enable_anomaly_investigation=True,
    )
    events: list[tuple[str, dict]] = []
    state, report = agent.run(make_state(), on_event=lambda t, p: events.append((t, p)))
    assert report.anomalies and report.anomalies[0].tag == "one_time_event"
    assert report.verification["ok"] is True            # 45000.0 / 92.0 traced to results
    assert state.anomalies[0]["title"] == "March spike"
    types = [t for t, _ in events]
    assert "plan_ready" in types and "analysis_complete" in types
    assert types.count("step_started") == 3             # clean + step 1 + investigation


def test_no_anomaly_candidates_skips_investigation():
    agent, llm, sandbox = build_agent(
        [text_response(PLAN_JSON),
         tool_response("clean code"),
         tool_response("step code"),
         text_response("[]"),                            # no anomalies found
         text_response(GOOD_REPORT)],
        [CLEAN_OK, STEP_OK],
        enable_anomaly_investigation=True,
    )
    state, report = agent.run(make_state())
    assert report.anomalies == []
    assert len(state.step_results) == 2


def test_parse_json_tolerates_fences():
    from api.services.llm import LLMClient

    assert LLMClient.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert LLMClient.parse_json('noise {"a": 1} trailing') == {"a": 1}
    with pytest.raises(Exception):
        LLMClient.parse_json("no json here")
