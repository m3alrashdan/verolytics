"""v3 reasoning-engine tests: the self-critique / reflexion pass.

These exercise AnalystAgent._self_critique directly with a scripted LLM (no
sandbox, no network), proving the draft → critique → revise behaviour and that
any critique failure safely leaves the draft untouched.
"""
from __future__ import annotations

import json

import pytest

from api.config import Settings
from api.services.agent import AnalystAgent
from tests.test_agent import FakeLLM, make_state, text_response


def _agent(responses, **overrides) -> AnalystAgent:
    settings = Settings(_env_file=None, anthropic_api_key="test",
                        enable_self_critique=True, max_critique_passes=1, **overrides)
    # sandbox is unused by _self_critique; pass a sentinel that would error if touched
    return AnalystAgent(llm=FakeLLM(responses), sandbox=object(), settings=settings)


RESULTS_JSON = json.dumps({"steps": {"step_1": {"scalars": {"total": 4200.5}}}})
DRAFT = {"title": "Draft", "executive_summary": "Total is 4200.5.",
         "kpis": [{"label": "Total", "value": "4200.5"}], "findings": [], "recommendations": []}
REVISED = {"title": "Revised", "executive_summary": "Total is 4200.5, up across the period.",
           "kpis": [{"label": "Total", "value": "4200.5"}],
           "findings": [{"title": "Driver", "narrative": "4200.5 concentrated in one group."}],
           "recommendations": ["Act on the 4200.5 concentration."]}


def test_self_critique_revises_when_issues_found():
    critique = {"verdict": "revise",
                "issues": [{"severity": "high", "area": "finding",
                            "problem": "no findings", "fix": "add the driver finding"}],
                "missing_insights": ["the concentration of the total in one group"]}
    agent = _agent([text_response(json.dumps(critique)), text_response(json.dumps(REVISED))])
    data, text = agent._self_critique("sys", RESULTS_JSON, dict(DRAFT), json.dumps(DRAFT),
                                      make_state(), lambda s: None)
    assert data["title"] == "Revised"
    assert data["findings"] and "Driver" in data["findings"][0]["title"]
    assert json.loads(text)["title"] == "Revised"
    # critique + revision = exactly two model calls
    assert len(agent.llm.calls) == 2


def test_self_critique_accepts_clean_draft_without_revising():
    critique = {"verdict": "accept", "issues": [], "missing_insights": []}
    agent = _agent([text_response(json.dumps(critique))])
    data, text = agent._self_critique("sys", RESULTS_JSON, dict(DRAFT), json.dumps(DRAFT),
                                      make_state(), lambda s: None)
    assert data["title"] == "Draft"          # untouched
    assert len(agent.llm.calls) == 1          # no revision call


def test_self_critique_keeps_draft_on_malformed_critique():
    # Two non-JSON replies (initial + retry) must not corrupt or drop the draft.
    agent = _agent([text_response("not json at all"), text_response("still prose")])
    data, _ = agent._self_critique("sys", RESULTS_JSON, dict(DRAFT), json.dumps(DRAFT),
                                   make_state(), lambda s: None)
    assert data["title"] == "Draft"


def test_self_critique_retries_when_first_reply_is_prose():
    # Free models sometimes answer prose first; a JSON-only retry should recover.
    critique_accept = {"verdict": "accept", "issues": [], "missing_insights": []}
    agent = _agent([text_response("Sure, here is my review:"),
                    text_response(json.dumps(critique_accept))])
    data, _ = agent._self_critique("sys", RESULTS_JSON, dict(DRAFT), json.dumps(DRAFT),
                                   make_state(), lambda s: None)
    assert data["title"] == "Draft"          # accepted after retry → no revision
    assert len(agent.llm.calls) == 2          # prose attempt + successful retry


def test_self_critique_ignores_low_severity_only():
    critique = {"verdict": "revise",
                "issues": [{"severity": "low", "area": "summary", "problem": "nit", "fix": "tweak"}],
                "missing_insights": []}
    agent = _agent([text_response(json.dumps(critique))])
    data, _ = agent._self_critique("sys", RESULTS_JSON, dict(DRAFT), json.dumps(DRAFT),
                                   make_state(), lambda s: None)
    assert data["title"] == "Draft"          # low-only → no revision
    assert len(agent.llm.calls) == 1
