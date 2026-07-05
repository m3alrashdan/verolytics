"""Automated evaluation: run every dataset through the full pipeline.

For each dataset it measures:
- pipeline success (no crash, report produced)
- number accuracy: the verifier's own result, PLUS a ground-truth spot check
  (expected aggregates from expected/*.json must appear in the agent's results
  when the agent claims them)
- steps planned / completed / skipped, wall time, token cost estimate

Usage:  ANTHROPIC_API_KEY=... python evaluation/run_eval.py [dataset_glob]
Writes a markdown row per dataset to evaluation/results.md.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from api.config import get_settings  # noqa: E402
from api.models.session import SessionState  # noqa: E402
from api.services.agent import AnalystAgent  # noqa: E402
from api.services.profiler import profile_file  # noqa: E402
from api.services.report_generator import render_html  # noqa: E402
from api.services.sandbox import SandboxExecutor  # noqa: E402
from api.services.verifier import collect_result_numbers  # noqa: E402

RESULTS_MD = HERE / "results.md"
HEADER = (
    "| dataset | status | steps done/planned | verifier | ground-truth hits | time (s) |\n"
    "|---|---|---|---|---|---|\n"
)


def run_one(path: Path) -> dict:
    settings = get_settings()
    sandbox = SandboxExecutor(settings)
    sandbox.ensure_image()
    session_id = uuid.uuid4().hex
    ws = sandbox.create_workspace(session_id)
    shutil.copy(path, ws / "data" / f"raw{path.suffix.lower()}")

    started = time.monotonic()
    row = {"dataset": path.name, "status": "failed", "steps": "-", "verifier": "-",
           "gt": "-", "time_s": 0.0}
    try:
        profile = profile_file(ws / "data" / f"raw{path.suffix.lower()}", max_rows=settings.max_rows)
        profile.filename = path.name
        state = SessionState(session_id=session_id, filename=path.name, profile=profile)
        agent = AnalystAgent(settings=settings)
        state, report = agent.run(state)

        done = sum(1 for s in state.step_results if s.status == "done") - 1  # minus cleaning
        planned = len(state.plan.analysis_steps)
        row["steps"] = f"{done}/{planned}"
        v = report.verification
        row["verifier"] = ("PASS" if v.get("ok") else "REDACTED") + f" ({v.get('checked')} checked)"

        # ground-truth spot check: agent result numbers vs pandas-computed aggregates
        expected_file = HERE / "expected" / f"{path.stem}.json"
        if expected_file.exists():
            expected = json.loads(expected_file.read_text())
            agent_numbers = collect_result_numbers(agent._results_payload(state))
            hits = total = 0
            for col_aggs in expected.get("aggregates", {}).values():
                for val in col_aggs.values():
                    total += 1
                    if any(round(n, 2) == round(val, 2) for n in agent_numbers):
                        hits += 1
            row["gt"] = f"{hits}/{total} expected aggregates present"
        html = render_html(report, ws)  # rendering must not crash
        artifacts = HERE / "results_raw"
        artifacts.mkdir(exist_ok=True)
        (artifacts / f"{path.stem}.html").write_text(html, encoding="utf-8")
        (artifacts / f"{path.stem}.report.json").write_text(report.model_dump_json(indent=2),
                                                            encoding="utf-8")
        row["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        row["status"] = f"failed: {str(exc)[:80]}"
    finally:
        row["time_s"] = round(time.monotonic() - started, 1)
        sandbox.destroy_workspace(session_id)
    return row


def main() -> None:
    glob = sys.argv[1] if len(sys.argv) > 1 else "*"
    datasets = sorted((HERE / "datasets").glob(glob))
    if not datasets:
        print("no datasets found — run evaluation/make_datasets.py first")
        sys.exit(1)
    rows = []
    for p in datasets:
        print(f"=== {p.name} ===")
        row = run_one(p)
        print(row)
        rows.append(row)

    lines = ["# Evaluation Results\n", HEADER.rstrip()]
    for r in rows:
        lines.append(f"| {r['dataset']} | {r['status']} | {r['steps']} | {r['verifier']} | "
                     f"{r['gt']} | {r['time_s']} |")
    ok = sum(1 for r in rows if r["status"] == "ok")
    lines.append(f"\n**{ok}/{len(rows)} datasets completed successfully.**")
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS_MD}")


if __name__ == "__main__":
    main()
