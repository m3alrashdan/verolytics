"""ML prediction tests: run_prediction extracts metrics, values and chart from
the sandbox result and keeps the narrative verified (scripted LLM + sandbox)."""
from __future__ import annotations

from api.config import Settings
from api.models.session import ChartArtifact, ExecutionResult
from api.services.agent import AnalystAgent
from tests.test_agent import FakeLLM, FakeSandbox, make_state, text_response, tool_response


def _agent(llm_responses, sandbox_results):
    settings = Settings(_env_file=None, anthropic_api_key="test", enable_self_critique=False)
    return AnalystAgent(llm=FakeLLM(llm_responses), sandbox=FakeSandbox(sandbox_results),
                        settings=settings)


def test_run_prediction_surfaces_metrics_values_and_chart():
    metrics = {"model": "RandomForest", "mape": 8.2, "rmse": 1234.5, "mae": 900.0,
               "r2": 0.91, "train_rows": 580, "test_rows": 145, "horizon": 12,
               "target": "revenue", "is_time_series": True}
    pred_result = ExecutionResult(
        ok=True,
        scalars={"prediction_metrics": metrics},
        tables={"prediction_values": {
            "columns": ["period", "predicted", "lower", "upper"],
            "rows": [{"period": "2025-01", "predicted": 51000.0, "lower": 48000.0, "upper": 54000.0}],
            "n_rows_total": 12,
        }},
        charts=[ChartArtifact(name="prediction_chart", title="Forecast",
                              html_path="charts/prediction_chart.html")],
    )
    # tool call (runs the code) -> then a narrative answer citing result numbers
    agent = _agent(
        [tool_response("# train + forecast"),
         text_response("RandomForest won with MAPE 8.2% and r2 0.91; revenue ~51000 next period.")],
        [pred_result],
    )
    out = agent.run_prediction(make_state(), target="revenue", horizon=12)

    assert out["metrics"]["model"] == "RandomForest"
    assert out["metrics"]["mape"] == 8.2 and out["metrics"]["r2"] == 0.91
    assert out["values"]["columns"][:2] == ["period", "predicted"]
    assert out["values"]["rows"][0]["predicted"] == 51000.0
    assert out["chart"]["name"] == "prediction_chart"
    # the narrative only cites result numbers → verified, not redacted
    assert out["verification"]["ok"] is True
    assert "[unverified]" not in out["answer"]


def test_run_prediction_redacts_unsupported_numbers():
    # complete result (metrics + values) so the fallback is NOT triggered
    pred_result = ExecutionResult(
        ok=True,
        scalars={"prediction_metrics": {"model": "GBM", "mape": 5.0, "r2": 0.95}},
        tables={"prediction_values": {"columns": ["period", "predicted"],
                                      "rows": [{"period": 1, "predicted": 10.0}], "n_rows_total": 1}},
        charts=[],
    )
    agent = _agent(
        [tool_response("# code"),
         text_response("Accuracy was 5.0% but revenue will hit 999999 next year.")],
        [pred_result],
    )
    out = agent.run_prediction(make_state())
    # 999999 isn't in the results → redacted; 5.0 is fine
    assert "[unverified]" in out["answer"]
    assert out["verification"]["ok"] is False
    assert out["method"] == "model"


def test_run_prediction_falls_back_when_model_incomplete():
    # model produced nothing usable; the deterministic fallback supplies the result
    empty = ExecutionResult(ok=True, scalars={}, tables={}, charts=[])
    fallback = ExecutionResult(
        ok=True,
        scalars={"prediction_metrics": {"model": "GradientBoosting", "mape": 5.29, "r2": 0.3},
                 "prediction_summary": "Best model GradientBoosting: MAPE 5.29%, R2 0.3."},
        tables={"prediction_values": {"columns": ["period", "predicted", "lower", "upper"],
                                      "rows": [{"period": "2025-01", "predicted": 1750.56,
                                                "lower": 1616.46, "upper": 1884.66}], "n_rows_total": 6}},
        charts=[ChartArtifact(name="prediction_chart", title="Forecast",
                              html_path="charts/prediction_chart.html")],
    )
    agent = _agent(
        [tool_response("# model's attempt"), text_response("I tried but could not save results.")],
        [empty, fallback],   # 1st consumed by the qa loop, 2nd by the fallback execute
    )
    out = agent.run_prediction(make_state(), target="revenue", horizon=6)
    assert out["method"] == "fallback"
    assert out["metrics"]["model"] == "GradientBoosting" and out["metrics"]["mape"] == 5.29
    assert out["values"]["rows"][0]["predicted"] == 1750.56
    assert out["chart"]["name"] == "prediction_chart"
    assert out["verification"]["ok"] is True       # summary cites only result numbers
    assert "5.29" in out["answer"]
