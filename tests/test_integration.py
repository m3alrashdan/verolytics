"""Full-pipeline integration test: scripted LLM, REAL sandbox, real verification.

Requires Docker + the sandbox image (same marker as test_sandbox).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from api.config import Settings
from api.models.session import SessionState
from api.services.agent import AnalystAgent
from api.services.profiler import profile_file
from api.services.report_generator import render_html
from api.services.sandbox import SandboxExecutor
from tests.test_agent import FakeLLM, text_response, tool_response
from tests.test_sandbox import _docker_ready

pytestmark = [pytest.mark.sandbox,
              pytest.mark.skipif(not _docker_ready(), reason="docker/sandbox image unavailable")]

DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "datasets" / "14_minimal.csv"

CLEAN_CODE = """
df = pd.read_csv(DATA_DIR + '/raw.csv')
before = len(df)
df = df.drop_duplicates()
log = [{"action": "drop_duplicates", "column": None, "before_count": before,
        "after_count": len(df), "justification": "exact duplicate rows add no information"}]
df.to_parquet(DATA_DIR + '/cleaned.parquet')
save_value("cleaning_log", log)
save_value("cleaned_shape", {"rows": len(df), "cols": df.shape[1]})
"""

STEP_CODE = """
df = pd.read_parquet(DATA_DIR + '/cleaned.parquet')
by_region = df.groupby('region', as_index=False)['revenue'].sum().round(2)
save_table("revenue_by_region", by_region)
save_value("total_revenue", round(float(df['revenue'].sum()), 2))
fig = px.bar(by_region, x='region', y='revenue', title='Revenue by region')
save_chart("revenue_by_region", fig, title="Revenue by region")
"""


@pytest.mark.skipif(not DATASET.exists(), reason="run evaluation/make_datasets.py first")
def test_full_pipeline_with_real_sandbox(tmp_path):
    settings = Settings(_env_file=None, anthropic_api_key="offline", workspace_root=tmp_path,
                        enable_anomaly_investigation=False)
    sandbox = SandboxExecutor(settings)
    sid = "e2etest1"
    ws = sandbox.create_workspace(sid)
    shutil.copy(DATASET, ws / "data" / "raw.csv")

    total = round(pd.read_csv(DATASET)["revenue"].sum(), 2)
    plan = json.dumps({"cleaning_plan": ["drop exact duplicates"],
                       "analysis_steps": [{"step_number": 1, "description": "totals by region",
                                           "rationale": "overview"}]})
    report_json = json.dumps({
        "title": "Minimal sales analysis",
        "executive_summary": f"Total revenue across all regions reached {total}.",
        "kpis": [{"label": "Total revenue", "value": str(total)}],
        "findings": [{"title": "Regional revenue", "narrative": f"Combined revenue was {total}.",
                      "chart_name": "revenue_by_region"}],
        "data_quality_notes": "Duplicates removed.",
        "forecast": None,
        "recommendations": [f"Track the {total} baseline monthly."],
    })

    llm = FakeLLM([text_response(plan), tool_response(CLEAN_CODE),
                   tool_response(STEP_CODE), text_response(report_json)])
    agent = AnalystAgent(llm=llm, sandbox=sandbox, settings=settings)
    profile = profile_file(ws / "data" / "raw.csv")
    state = SessionState(session_id=sid, filename="raw.csv", profile=profile)

    state, report = agent.run(state)

    assert state.status.value == "done"
    assert report.verification["ok"] is True
    assert state.cleaning_log and state.cleaning_log[0]["action"] == "drop_duplicates"
    html = render_html(report, ws)
    assert "Revenue by region" in html
    # interactive chart html exists; png exists for the PDF path (kaleido)
    assert (ws / report.charts[0].html_path).exists()
