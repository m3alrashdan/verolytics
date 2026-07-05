"""Agent orchestrator: plan -> clean -> execute steps -> interpret -> verify.

The LLM never computes numbers. It plans, writes code for the sandbox, and
interprets structured results. The verifier gate rejects any report narrative
containing numbers that cannot be traced back to sandbox results.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from api.config import Settings, get_settings
from api.models.report import (
    ChartMeta, CleaningLogEntry, Finding, ForecastSection, KPI, Report,
)
from api.models.session import (
    AnalysisPlan, ExecutionResult, PlanStep, SessionState, SessionStatus, StepResult,
)
from api.prompts.followup import followup_prompt
from api.prompts.interpretation import (
    CRITIQUE_PROMPT, EMPTY_REPORT_REPROMPT, REVISION_PROMPT, VERIFICATION_FAILURE_PROMPT,
    interpretation_prompt,
)
from api.prompts.investigation import ANOMALY_CANDIDATES_PROMPT, INVESTIGATE_PROMPT
from api.prompts.planning import RETRY_PROMPT, STEP_PROMPT, cleaning_prompt, planning_prompt
from api.prompts.prediction import FALLBACK_PREDICT_CODE, PREDICT_PROMPT
from api.prompts.scenario import SCENARIO_PROMPT, TRANSFORM_PROMPT
from api.prompts.system import LANGUAGE_NAMES, system_prompt
from api.services.llm import EXECUTE_PYTHON_TOOL, LLMClient, LLMError
from api.services.sandbox import SandboxExecutor
from api.services.verifier import collect_result_numbers, redact_unverified, verify_report

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 4_000
RESULTS_JSON_MAX_TABLE_ROWS = 50

ProgressFn = Callable[[SessionState], None]
EventFn = Callable[[str, dict], None]  # (event_type, payload)


class AgentError(RuntimeError):
    pass


def _repair_generated_code(code: str) -> str:
    """Best-effort repair of syntactically broken model output.

    Smaller / OpenAI-compatible models (e.g. local Ollama qwen) frequently
    over-escape the Python they emit inside the tool-call JSON: quotes become
    ``{\\'rows\\': 1}`` and, more damagingly, line breaks/tabs arrive as the
    literal two-character sequences ``\\n`` / ``\\t`` so the whole program lands
    on "line 1" and fails to compile. Each repair is only accepted when the
    original fails to compile *and* the rewrite compiles, so valid code with
    genuine in-string escapes is never touched.
    """
    if not code:
        return code
    try:
        compile(code, "<user_code>", "exec")
        return code
    except SyntaxError:
        pass

    def _unescape_ws(s: str) -> str:
        return (s.replace("\\r\\n", "\n").replace("\\n", "\n")
                 .replace("\\t", "\t").replace("\\r", "\n"))

    unquoted = code.replace("\\'", "'").replace('\\"', '"')
    # ordered from least to most aggressive; first one that compiles wins
    for repaired in (unquoted, _unescape_ws(code), _unescape_ws(unquoted)):
        if repaired == code:
            continue
        try:
            compile(repaired, "<user_code>", "exec")
            logger.info("repaired over-escaped generated code")
            return repaired
        except SyntaxError:
            continue
    return code  # let the real error surface and drive a retry


def _extract_code_fallback(text: str) -> str | None:
    """Pull Python out of a model reply that ignored the forced tool call.

    Weaker models / Ollama don't always honour ``tool_choice`` and instead
    answer with a ```python fenced block. Recover that code so the run can
    proceed instead of wasting the attempt.
    """
    if not text:
        return None

    def _accept(code: str | None) -> str | None:
        if not code or not code.strip():
            return None
        for cand in (code, _repair_generated_code(code)):
            try:
                compile(cand, "<user_code>", "exec")
                return cand
            except SyntaxError:
                continue
        return None

    # 1) Some models (e.g. qwen2.5-coder via Ollama) don't honour the tool
    #    protocol and instead print the call as JSON in the content:
    #    {"name": "execute_python", "arguments": {"code": "..."}}. Recover the
    #    code from the largest JSON object that carries a `code` field.
    for block in sorted(re.findall(r"\{.*?\}(?=\s*$)|\{.*\}", text, re.DOTALL), key=len, reverse=True):
        try:
            obj = json.loads(block, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        args = obj.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args, strict=False)
            except (json.JSONDecodeError, ValueError):
                args = None
        code = (args.get("code") if isinstance(args, dict) else None) or obj.get("code")
        accepted = _accept(code if isinstance(code, str) else None)
        if accepted:
            return accepted

    # 2) Otherwise pull the largest ```python fenced block.
    fences = re.findall(r"```(?:python|py)?\s*(.*?)```", text, re.DOTALL)
    candidate = max(fences, key=len).strip() if fences else ""
    return _accept(candidate)


class AnalystAgent:
    def __init__(self, llm: LLMClient | None = None,
                 sandbox: SandboxExecutor | None = None,
                 settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or LLMClient(self.settings)
        self.sandbox = sandbox or SandboxExecutor(self.settings)

    # ------------------------------------------------------------------ run --

    def run(self, state: SessionState, on_progress: ProgressFn | None = None,
            on_event: EventFn | None = None) -> tuple[SessionState, Report]:
        """Run the full pipeline for an uploaded, profiled session."""
        self._session_id = state.session_id
        notify = on_progress or (lambda s: None)
        self._emit = on_event or (lambda t, p: None)
        profile_json = state.profile.model_dump_json(indent=None)
        system = system_prompt(state.language)

        # 1. PLAN ----------------------------------------------------------------
        state.status, state.progress, state.progress_message = SessionStatus.PLANNING, 0.05, "Planning analysis"
        notify(state)
        plan_resp = self.llm.create(system=system, messages=[{
            "role": "user",
            "content": planning_prompt(profile_json, state.goal,
                                       self.settings.max_analysis_steps,
                                       self.settings.forecast_min_points),
        }])
        plan_data = self.llm.parse_json(self.llm.text_of(plan_resp))
        plan = AnalysisPlan.model_validate(plan_data)
        plan.analysis_steps = plan.analysis_steps[: self.settings.max_analysis_steps]
        state.plan = plan
        logger.info("session=%s plan: %d cleaning actions, %d steps",
                    state.session_id, len(plan.cleaning_plan), len(plan.analysis_steps))
        self._emit("plan_ready", {"cleaning_plan": plan.cleaning_plan,
                                  "steps": [s.model_dump() for s in plan.analysis_steps]})

        # Conversation used for all code generation (keeps error context around)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": planning_prompt(profile_json, state.goal,
                                                        self.settings.max_analysis_steps,
                                                        self.settings.forecast_min_points)},
            {"role": "assistant", "content": json.dumps(plan_data)},
        ]

        # 2. CLEAN ---------------------------------------------------------------
        state.status, state.progress, state.progress_message = SessionStatus.CLEANING, 0.12, "Cleaning data"
        notify(state)
        self._emit("step_started", {"step_number": 0, "description": "Data cleaning"})
        clean_result, clean_code, _ = self._code_loop(system, messages, cleaning_prompt(state.filename))
        clean_ok = clean_result is not None and clean_result.ok
        if not clean_ok:
            # Cleaning is best-effort: a weak model may never emit usable cleaning
            # code. Rather than abort the whole analysis, fall back to the raw data
            # (converted to cleaned.parquet) and carry on.
            logger.warning("session=%s cleaning did not succeed (%s); proceeding with raw data",
                           state.session_id,
                           clean_result.error if clean_result else "no executable code produced")
        # Safety net: guarantee cleaned.parquet exists (every later step loads it),
        # whether the model forgot to persist it or cleaning failed outright.
        self._ensure_cleaned_parquet(state.filename)
        cleaning_log = (clean_result.scalars.get("cleaning_log") if clean_ok else None) or []
        self._emit("step_completed", {"step_number": 0, "description": "Data cleaning",
                                      "duration_s": clean_result.duration_s if clean_result else 0.0,
                                      "cleaning_log": cleaning_log})
        state.cleaning_log = list(cleaning_log)
        cleaning_step = StepResult(
            step=PlanStep(step_number=0, description="Data cleaning", rationale="Prepare data for analysis"),
            status="done" if clean_ok else "skipped", code=clean_code, result=clean_result,
        )
        state.step_results.append(cleaning_step)

        # 3. ANALYSIS STEPS --------------------------------------------------------
        n = max(len(plan.analysis_steps), 1)
        for i, step in enumerate(plan.analysis_steps):
            state.status = SessionStatus.ANALYZING
            state.progress = 0.15 + 0.6 * (i / n)
            state.progress_message = f"Step {step.step_number}/{len(plan.analysis_steps)}: {step.description}"
            notify(state)
            prompt = STEP_PROMPT.format(step_number=step.step_number,
                                        description=step.description,
                                        hypothesis=step.hypothesis or "(none specified)",
                                        rationale=step.rationale)
            self._emit("step_started", {"step_number": step.step_number, "description": step.description})
            result, code, attempts = self._code_loop(system, messages, prompt)
            if result is not None and result.ok:
                state.step_results.append(StepResult(step=step, status="done", attempts=attempts,
                                                     code=code, result=result))
                self._emit("step_completed", {
                    "step_number": step.step_number, "description": step.description,
                    "duration_s": result.duration_s, "attempts": attempts,
                    "charts": [c.model_dump() for c in result.charts]})
                for c in result.charts:
                    self._emit("chart_ready", c.model_dump())
            else:
                reason = (result.error if result else "no executable code produced")
                logger.warning("session=%s step %d skipped after %d attempts: %s",
                               state.session_id, step.step_number, attempts, reason)
                state.step_results.append(StepResult(step=step, status="skipped", attempts=attempts,
                                                     code=code, skip_reason=reason))
                self._emit("step_failed", {"step_number": step.step_number,
                                           "description": step.description,
                                           "attempts": attempts, "error": reason})

        # 4. ANOMALY INVESTIGATION ----------------------------------------------------
        if self.settings.enable_anomaly_investigation:
            self._investigate_anomalies(state, system, messages, notify)

        # 5. INTERPRET + 6. VERIFY ---------------------------------------------------
        state.status, state.progress, state.progress_message = SessionStatus.INTERPRETING, 0.8, "Writing report"
        notify(state)
        self._emit("report_generating", {})
        report = self._interpret_and_verify(state, system, notify)
        state.status, state.progress, state.progress_message = SessionStatus.DONE, 1.0, "Report ready"
        notify(state)
        self._emit("analysis_complete", {"verification": report.verification})
        return state, report

    # ------------------------------------------------- anomaly investigation --

    def _investigate_anomalies(self, state: SessionState, system: str,
                               messages: list[dict[str, Any]], notify: ProgressFn) -> None:
        """Smart Data Detective: pick anomalies from results, drill down on each."""
        results_json = json.dumps(self._results_payload(state), ensure_ascii=False, default=str)
        try:
            resp = self.llm.create(system=system, messages=[{
                "role": "user",
                "content": ANOMALY_CANDIDATES_PROMPT.format(
                    max_anomalies=self.settings.max_anomaly_investigations,
                    results_json=results_json),
            }])
            candidates = self.llm.parse_json(self.llm.text_of(resp))
        except Exception:  # noqa: BLE001 — investigation is best-effort
            logger.exception("session=%s anomaly candidate detection failed", state.session_id)
            return
        if not isinstance(candidates, list) or not candidates:
            return
        candidates = candidates[: self.settings.max_anomaly_investigations]
        state.progress_message = "Investigating anomalies"
        notify(state)
        next_no = max((sr.step.step_number for sr in state.step_results), default=0) + 1
        for i, cand in enumerate(candidates):
            title = str(cand.get("title", f"anomaly {i + 1}"))
            self._emit("step_started", {"step_number": next_no + i,
                                        "description": f"Investigating: {title}"})
            prompt = INVESTIGATE_PROMPT.format(
                title=title, context=str(cand.get("context", "")),
                key=f"anomaly_{i + 1}")
            result, code, attempts = self._code_loop(system, messages, prompt)
            step = PlanStep(step_number=next_no + i,
                            description=f"Anomaly investigation: {title}",
                            rationale=str(cand.get("context", "")))
            if result is not None and result.ok:
                state.step_results.append(StepResult(step=step, status="done",
                                                     attempts=attempts, code=code, result=result))
                state.anomalies.append({"title": title, "context": cand.get("context")})
                self._emit("step_completed", {"step_number": step.step_number,
                                              "description": step.description,
                                              "duration_s": result.duration_s,
                                              "charts": [c.model_dump() for c in result.charts]})
            else:
                state.step_results.append(StepResult(step=step, status="skipped", attempts=attempts,
                                                     code=code,
                                                     skip_reason=result.error if result else "no code"))
                self._emit("step_failed", {"step_number": step.step_number,
                                           "description": step.description,
                                           "error": result.error if result else "no code"})

    # ------------------------------------------------------------- code loop --

    def _ensure_cleaned_parquet(self, filename: str) -> None:
        """Create DATA_DIR/cleaned.parquet from the raw file if cleaning didn't.

        Downstream steps always load cleaned.parquet, so a missing file would
        skip every step. ``os``/``glob`` are blocked in the sandbox, so we
        detect the missing file on the host and convert the raw file in-sandbox.
        """
        data_dir = self.sandbox.workspace(self._session_id) / "data"
        if (data_dir / "cleaned.parquet").exists():
            return
        suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ".csv"
        reader = "pd.read_excel" if suffix in (".xlsx", ".xls") else "pd.read_csv"
        logger.warning("session=%s cleaning produced no cleaned.parquet; creating it from raw%s",
                       self._session_id, suffix)
        snippet = (
            f"df = {reader}(DATA_DIR + '/raw{suffix}')\n"
            "df.to_parquet(DATA_DIR + '/cleaned.parquet')\n"
            "save_value('cleaned_shape', {'rows': len(df), 'cols': df.shape[1]})\n"
        )
        self.sandbox.execute(self._session_id, snippet)

    def _code_loop(self, system: str, messages: list[dict[str, Any]],
                   user_prompt: str) -> tuple[ExecutionResult | None, str | None, int]:
        """Ask the model for code, execute it, retry on failure (max retries)."""
        messages.append({"role": "user", "content": user_prompt})
        last_result: ExecutionResult | None = None
        last_code: str | None = None
        attempts = 0
        while attempts < self.settings.max_step_retries:
            attempts += 1
            response = self.llm.create(
                system=system, messages=messages,
                tools=[EXECUTE_PYTHON_TOOL],
                tool_choice={"type": "tool", "name": "execute_python"},
            )
            tool_use = self.llm.tool_use_of(response)
            if tool_use is None:  # model ignored the forced tool choice
                fallback = _extract_code_fallback(self.llm.text_of(response))
                if fallback is not None:
                    last_code = fallback
                    self._emit("code_executing", {"code": last_code[:4000], "attempt": attempts})
                    result = self.sandbox.execute(self._session_id, last_code)
                    last_result = result
                    messages.append({"role": "assistant", "content": self.llm.text_of(response)})
                    if result.ok:
                        return result, last_code, attempts
                    messages.append({"role": "user", "content":
                        f"That code failed:\n{self._tool_result_text(result)}\n{RETRY_PROMPT} "
                        "You MUST call the execute_python tool."})
                    continue
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content":
                    "You did not call the tool. Call execute_python with the code as its `code` argument."})
                continue
            last_code = _repair_generated_code(str(tool_use.input.get("code", "")))
            self._emit("code_executing", {"code": last_code[:4000], "attempt": attempts})
            result = self.sandbox.execute(self._session_id, last_code)
            last_result = result
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": self._tool_result_text(result),
                "is_error": not result.ok,
            }]})
            if result.ok:
                return result, last_code, attempts
            messages.append({"role": "user", "content": RETRY_PROMPT})
        return last_result, last_code, attempts

    @staticmethod
    def _tool_result_text(result: ExecutionResult) -> str:
        payload = result.model_dump()
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > TOOL_RESULT_MAX_CHARS:
            slim = {
                "ok": result.ok, "error": result.error, "traceback": result.traceback,
                "stdout": result.stdout[:1000],
                "tables_saved": {k: {"columns": v.get("columns"), "n_rows_total": v.get("n_rows_total"),
                                     "rows_preview": (v.get("rows") or [])[:5]}
                                 for k, v in result.tables.items()},
                "scalars": result.scalars,
                "charts": [c.model_dump() for c in result.charts],
            }
            text = json.dumps(slim, ensure_ascii=False, default=str)[:TOOL_RESULT_MAX_CHARS]
        return text

    # ------------------------------------------------------- interpretation --

    def _results_payload(self, state: SessionState) -> dict[str, Any]:
        """Structured results JSON: the ONLY source of numbers for the report."""
        steps: dict[str, Any] = {}
        for sr in state.step_results:
            if sr.status != "done" or sr.result is None:
                steps[f"step_{sr.step.step_number}"] = {
                    "description": sr.step.description, "status": "skipped",
                    "skip_reason": sr.skip_reason,
                }
                continue
            tables = {}
            for name, t in sr.result.tables.items():
                tables[name] = {**t, "rows": (t.get("rows") or [])[:RESULTS_JSON_MAX_TABLE_ROWS]}
            steps[f"step_{sr.step.step_number}"] = {
                "description": sr.step.description, "status": "done",
                "tables": tables, "scalars": sr.result.scalars,
                "charts": [c.name for c in sr.result.charts],
            }
        return {"cleaning_log": state.cleaning_log, "steps": steps}

    def _all_charts(self, state: SessionState) -> list[ChartMeta]:
        charts: list[ChartMeta] = []
        for sr in state.step_results:
            if sr.result:
                charts.extend(ChartMeta(**c.model_dump()) for c in sr.result.charts)
        return charts

    @staticmethod
    def _report_texts(data: dict[str, Any]) -> list[str]:
        texts = [data.get("title", ""), data.get("executive_summary", ""),
                 data.get("data_quality_notes") or ""]
        for k in data.get("kpis", []) or []:
            texts += [str(k.get("label", "")), str(k.get("value", "")), str(k.get("change") or "")]
        for f in data.get("findings", []) or []:
            texts += [str(f.get("title", "")), str(f.get("narrative", ""))]
        texts += [str(r) for r in data.get("recommendations", []) or []]
        fc = data.get("forecast")
        if fc:
            texts += [str(fc.get("narrative", "")), str(fc.get("reliability_statement", ""))]
        for a in data.get("anomalies", []) or []:
            texts += [str(a.get("title", "")), str(a.get("narrative", ""))]
        for s in data.get("segments", []) or []:
            texts += [str(s.get("name", "")), str(s.get("description", "")),
                      str(s.get("recommendation", ""))]
        return texts

    def _interpret_and_verify(self, state: SessionState, system: str, notify: ProgressFn) -> Report:
        results = self._results_payload(state)
        charts = self._all_charts(state)
        results_json = json.dumps(results, ensure_ascii=False, default=str)
        charts_json = json.dumps([c.model_dump() for c in charts], ensure_ascii=False)

        has_results = any(sr.status == "done" and sr.result for sr in state.step_results)
        interp = interpretation_prompt(results_json, charts_json, state.language)

        # Draft the report (robust to a prose reply), then run a self-critique
        # /reflexion pass that audits it against the computed results and revises
        # it. Verification (below) remains the final, non-negotiable gate.
        report_data: dict[str, Any] = self._json_call(system, interp, "report-draft") or {}
        report_text = json.dumps(report_data, ensure_ascii=False)
        if self.settings.enable_self_critique and report_data:
            report_data, report_text = self._self_critique(
                system, results_json, report_data, report_text, state, notify)

        # Quality floor: never ship an empty report when analysis actually
        # produced results — re-prompt once for a complete one.
        if has_results and not (report_data.get("findings") or report_data.get("kpis")):
            logger.info("session=%s empty report despite results; re-prompting", state.session_id)
            repaired = self._json_call(system, EMPTY_REPORT_REPROMPT.format(
                results_json=results_json, charts_json=charts_json,
                language_name=LANGUAGE_NAMES.get(state.language, "English")), "report-repair")
            if isinstance(repaired, dict) and (repaired.get("findings") or repaired.get("kpis")):
                report_data, report_text = repaired, json.dumps(repaired, ensure_ascii=False)

        # Verification loop: the report currently sits as the last assistant turn.
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": interp},
            {"role": "assistant", "content": report_text},
        ]
        verification = None
        for attempt in range(1, self.settings.max_verification_attempts + 1):
            state.status, state.progress_message = SessionStatus.VERIFYING, f"Verifying numbers (pass {attempt})"
            notify(state)
            verification = verify_report(self._report_texts(report_data), results)
            logger.info("session=%s verification pass %d: checked=%d unmatched=%s",
                        state.session_id, attempt, verification.checked, verification.unmatched)
            if verification.ok or attempt == self.settings.max_verification_attempts:
                break
            messages.append({"role": "user", "content": VERIFICATION_FAILURE_PROMPT.format(
                unmatched=", ".join(verification.unmatched))})
            regen = self._json_call_messages(system, messages, "report-fix")
            if not isinstance(regen, dict):
                break  # couldn't get a clean rewrite; fall through to redaction
            report_data = regen
            messages.append({"role": "assistant", "content": json.dumps(regen, ensure_ascii=False)})
        assert report_data is not None and verification is not None

        redacted = False
        if not verification.ok:
            # Last-resort guarantee: no unverified number ever reaches the reader.
            redacted = True
            logger.error("session=%s verification still failing after %d passes; redacting %s",
                         state.session_id, self.settings.max_verification_attempts, verification.unmatched)
            report_data = json.loads(redact_unverified(
                json.dumps(report_data, ensure_ascii=False), verification.unmatched))

        return self._build_report(state, report_data, charts, verification, redacted)

    def _self_critique(self, system: str, results_json: str, report_data: dict[str, Any],
                       report_text: str, state: SessionState,
                       notify: ProgressFn) -> tuple[dict[str, Any], str]:
        """Reflexion pass: audit the draft against the results, then revise.

        Best-effort and bounded — any failure (bad JSON, model error) leaves the
        draft untouched. Verification downstream is still the hard gate, so this
        can only improve quality, never weaken correctness guarantees.
        """
        from api.prompts.system import LANGUAGE_NAMES
        language_name = LANGUAGE_NAMES.get(state.language, "English")
        state.status, state.progress_message = SessionStatus.INTERPRETING, "Reviewing findings"
        notify(state)
        self._emit("report_critiquing", {})

        for _pass in range(max(1, self.settings.max_critique_passes)):
            critique = self._json_call(
                system, CRITIQUE_PROMPT.format(results_json=results_json, report_json=report_text),
                label="self-critique")
            if not isinstance(critique, dict):
                return report_data, report_text  # couldn't get a usable critique; keep draft

            issues = [i for i in (critique.get("issues") or [])
                      if isinstance(i, dict) and i.get("severity") in ("high", "medium")]
            missing = [m for m in (critique.get("missing_insights") or []) if m]
            logger.info("session=%s self-critique verdict=%s actionable_issues=%d missing=%d",
                        state.session_id, critique.get("verdict"), len(issues), len(missing))
            # Trust concrete signals, not the advisory verdict label: only revise
            # when there are high/medium issues or genuinely missing insights.
            if not issues and not missing:
                return report_data, report_text

            revised = self._json_call(
                system, REVISION_PROMPT.format(
                    results_json=results_json, report_json=report_text,
                    critique_json=json.dumps(critique, ensure_ascii=False),
                    language_name=language_name),
                label="revision")
            if not isinstance(revised, dict):
                return report_data, report_text  # keep draft if revision unusable
            report_data, report_text = revised, json.dumps(revised, ensure_ascii=False)
        return report_data, report_text

    def _json_call(self, system: str, content: str, label: str, retries: int = 1) -> Any | None:
        """One LLM round-trip expected to return JSON, with a JSON-only retry."""
        return self._json_call_messages(
            system, [{"role": "user", "content": content}], label, retries)

    def _json_call_messages(self, system: str, messages: list[dict[str, Any]],
                            label: str, retries: int = 1) -> Any | None:
        """Run a JSON-returning completion over ``messages``, with a JSON-only retry.

        Smaller models intermittently answer prose where JSON is required; a
        single corrective retry recovers most of those. Returns None if no valid
        JSON could be obtained (the caller decides the safe fallback)."""
        msgs = list(messages)
        for attempt in range(retries + 1):
            text = ""
            try:
                text = self.llm.text_of(self.llm.create(system=system, messages=msgs))
                return self.llm.parse_json(text)
            except Exception:  # noqa: BLE001 — recover or fall back
                if attempt >= retries:
                    logger.warning("session=%s %s returned no usable JSON after %d attempts",
                                   self._session_id, label, attempt + 1)
                    return None
                msgs = msgs + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content":
                     "Respond with ONLY a single valid JSON object — no prose, no markdown "
                     "fences, nothing before or after it."},
                ]
        return None

    def _build_report(self, state: SessionState, data: dict[str, Any],
                      charts: list[ChartMeta], verification, redacted: bool) -> Report:
        chart_by_name = {c.name: c for c in charts}
        findings = []
        code_by_chart: dict[str, str] = {}
        for sr in state.step_results:
            if sr.result and sr.code:
                for c in sr.result.charts:
                    code_by_chart[c.name] = sr.code
        for f in data.get("findings", []) or []:
            cn = f.get("chart_name")
            findings.append(Finding(
                title=str(f.get("title", "")), narrative=str(f.get("narrative", "")),
                chart_name=cn if cn in chart_by_name else None,
                code=code_by_chart.get(cn) if cn else None,
            ))
        fc = data.get("forecast")
        forecast = None
        if isinstance(fc, dict) and fc.get("narrative"):
            forecast = ForecastSection(
                narrative=str(fc.get("narrative", "")),
                model_name=fc.get("model_name"),
                mape=fc.get("mape"),
                chart_name=fc.get("chart_name") if fc.get("chart_name") in chart_by_name else None,
                reliability_statement=str(fc.get("reliability_statement", "")),
            )
        cleaning_entries = []
        for e in state.cleaning_log:
            if isinstance(e, dict):
                cleaning_entries.append(CleaningLogEntry(
                    action=str(e.get("action", "")), column=e.get("column"),
                    before_count=_as_int(e.get("before_count")), after_count=_as_int(e.get("after_count")),
                    justification=str(e.get("justification", "")),
                ))
        from api.models.report import AnomalyInsight, Segment

        anomalies = []
        for a in data.get("anomalies", []) or []:
            if isinstance(a, dict) and a.get("narrative"):
                cn = a.get("chart_name")
                anomalies.append(AnomalyInsight(
                    title=str(a.get("title", "")), narrative=str(a.get("narrative", "")),
                    tag=str(a.get("tag", "one_time_event")),
                    chart_name=cn if cn in chart_by_name else None))
        segments = [Segment(name=str(s.get("name", "")), description=str(s.get("description", "")),
                            recommendation=str(s.get("recommendation", "")))
                    for s in data.get("segments", []) or [] if isinstance(s, dict) and s.get("name")]
        return Report(
            session_id=state.session_id,
            language=state.language,
            anomalies=anomalies,
            segments=segments,
            title=str(data.get("title", "Data Analysis Report")),
            executive_summary=str(data.get("executive_summary", "")),
            kpis=[KPI.model_validate(k) for k in data.get("kpis", []) or []],
            findings=findings,
            cleaning_log=cleaning_entries,
            data_quality_notes=data.get("data_quality_notes"),
            forecast=forecast,
            recommendations=[str(r) for r in data.get("recommendations", []) or []],
            charts=charts,
            verification={**verification.model_dump(), "redacted": redacted},
        )

    # --------------------------------------------------------------- followup --

    def answer_question(self, state: SessionState, question: str) -> dict[str, Any]:
        """Follow-up Q&A: same code->result->interpretation loop, scoped small."""
        system = system_prompt(state.language)
        results = self._results_payload(state)
        results_summary = json.dumps(results, ensure_ascii=False, default=str)[:20_000]
        max_execs = 3
        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": followup_prompt(question, state.profile.model_dump_json(),
                                       results_summary, max_execs, state.language),
        }]
        executions = 0
        new_results: list[ExecutionResult] = []
        while True:
            response = self.llm.create(system=system, messages=messages, tools=[EXECUTE_PYTHON_TOOL])
            tool_use = self.llm.tool_use_of(response)
            if tool_use is None or executions >= max_execs:
                answer = self.llm.text_of(response)
                break
            executions += 1
            result = self.sandbox.execute(state.session_id, str(tool_use.input.get("code", "")))
            new_results.append(result)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_use.id,
                "content": self._tool_result_text(result), "is_error": not result.ok,
            }]})

        allowed = collect_result_numbers(results)
        for r in new_results:
            allowed |= collect_result_numbers(r.model_dump())
        verification = verify_report([answer], {"_": list(allowed)})
        if not verification.ok:
            answer = redact_unverified(answer, verification.unmatched)
        return {"answer": answer, "executions": executions,
                "verification": verification.model_dump()}

    # ------------------------------------------------------------- scenarios --

    def run_scenario(self, state: SessionState, description: str) -> dict[str, Any]:
        """What-if engine: Monte Carlo simulation grounded in the actual data."""
        prompt = SCENARIO_PROMPT.format(
            description=description,
            profile_json=state.profile.model_dump_json(),
            results_summary=json.dumps(self._results_payload(state),
                                       ensure_ascii=False, default=str)[:15_000],
            n_iterations=self.settings.scenario_iterations,
            language_name=LANGUAGE_NAMES.get(state.language, "English"),
        )
        answer, results, charts = self._qa_loop(state, prompt, max_execs=3)
        scalars: dict[str, Any] = {}
        for r in results:
            scalars.update(r.scalars)
        allowed = collect_result_numbers(self._results_payload(state))
        for r in results:
            allowed |= collect_result_numbers(r.model_dump())
        verification = verify_report([answer], {"_": list(allowed)})
        if not verification.ok:
            answer = redact_unverified(answer, verification.unmatched)
        return {
            "answer": answer,
            "expected_outcome": scalars.get("expected_outcome"),
            "best_case": scalars.get("best_case"),
            "worst_case": scalars.get("worst_case"),
            "baseline": scalars.get("baseline"),
            "charts": [c.model_dump() for c in charts],
            "verification": verification.model_dump(),
        }

    # ------------------------------------------------------------ prediction --

    def run_prediction(self, state: SessionState, target: str | None = None,
                       horizon: int | None = None, frequency: str | None = None,
                       model: str | None = None) -> dict[str, Any]:
        """ML forecast: train + evaluate + predict future values, with accuracy.

        Flexible across datasets (time-series or tabular). Returns the chosen
        model's accuracy metrics, the predicted values (with interval), and a
        chart — all sourced from sandbox execution, so the numbers are grounded.
        """
        horizon = int(horizon) if horizon else 12
        prompt = PREDICT_PROMPT.format(
            target=target or "auto",
            horizon=horizon,
            frequency=frequency or "auto",
            model=model or "auto",
            profile_json=state.profile.model_dump_json(),
            language_name=LANGUAGE_NAMES.get(state.language, "English"),
        )
        answer, results, charts = self._qa_loop(state, prompt, max_execs=2)

        metrics: dict[str, Any] = {}
        values: dict[str, Any] | None = None
        for r in results:
            if isinstance(r.scalars.get("prediction_metrics"), dict):
                metrics = r.scalars["prediction_metrics"]
            if "prediction_values" in r.tables:
                values = r.tables["prediction_values"]

        # Reliability net: if the model didn't produce a usable forecast, run a
        # deterministic sklearn forecaster so the feature works on any model.
        metrics_ok = bool(metrics) and "error" not in metrics
        used_fallback = False
        if not metrics_ok or values is None:
            logger.info("session=%s prediction incomplete from model; running fallback forecaster",
                        state.session_id)
            fb = self.sandbox.execute(state.session_id,
                                      self._fallback_predict_code(target, horizon, model))
            if fb.ok:
                used_fallback = True
                results.append(fb)
                charts.extend(fb.charts)
                if isinstance(fb.scalars.get("prediction_metrics"), dict):
                    metrics = fb.scalars["prediction_metrics"]
                if "prediction_values" in fb.tables:
                    values = fb.tables["prediction_values"]
                if fb.scalars.get("prediction_summary"):
                    answer = str(fb.scalars["prediction_summary"])
        if isinstance(metrics, dict) and metrics.get("error") and len((answer or "").strip()) < 40:
            answer = str(metrics["error"])

        chart = next((c for c in charts if c.name == "prediction_chart"),
                     charts[0] if charts else None)

        allowed = collect_result_numbers(self._results_payload(state))
        for r in results:
            allowed |= collect_result_numbers(r.model_dump())
        verification = verify_report([answer], {"_": list(allowed)})
        if not verification.ok:
            answer = redact_unverified(answer, verification.unmatched)

        return {
            "answer": answer,
            "metrics": metrics,
            "values": values,
            "chart": chart.model_dump() if chart else None,
            "method": "fallback" if used_fallback else "model",
            "verification": verification.model_dump(),
        }

    def _fallback_predict_code(self, target: str | None, horizon: int,
                               model: str | None = None) -> str:
        return (FALLBACK_PREDICT_CODE
                .replace("__TARGET__", repr(target) if target else "None")
                .replace("__MODEL__", repr(model) if model else "'auto'")
                .replace("__HORIZON__", str(int(horizon))))

    # ------------------------------------------------------------ transforms --

    def preview_transform(self, state: SessionState, instruction: str) -> dict[str, Any]:
        """NL data transformation: execute into transformed.parquet, return preview."""
        prompt = TRANSFORM_PROMPT.format(
            instruction=instruction,
            profile_json=state.profile.model_dump_json(),
            language_name=LANGUAGE_NAMES.get(state.language, "English"),
        )
        answer, results, _charts = self._qa_loop(state, prompt, max_execs=2)
        before = after = None
        summary: dict[str, Any] = {}
        for r in results:
            before = r.tables.get("before_sample", before)
            after = r.tables.get("after_sample", after)
            if isinstance(r.scalars.get("transform_summary"), dict):
                summary = r.scalars["transform_summary"]
        ws = self.sandbox.workspace(state.session_id)
        ready = (ws / "data" / "transformed.parquet").exists()
        return {"message": answer, "before_sample": before, "after_sample": after,
                "summary": summary, "ready_to_apply": ready}

    def _qa_loop(self, state: SessionState, first_prompt: str,
                 max_execs: int = 3) -> tuple[str, list[ExecutionResult], list]:
        """Shared tool loop for chat/scenario/transform: code -> result -> answer."""
        system = system_prompt(state.language)
        messages: list[dict[str, Any]] = [{"role": "user", "content": first_prompt}]
        executions = 0
        results: list[ExecutionResult] = []
        charts: list = []
        while True:
            response = self.llm.create(system=system, messages=messages,
                                       tools=[EXECUTE_PYTHON_TOOL])
            tool_use = self.llm.tool_use_of(response)
            if tool_use is None or executions >= max_execs:
                return self.llm.text_of(response), results, charts
            executions += 1
            result = self.sandbox.execute(state.session_id, str(tool_use.input.get("code", "")))
            results.append(result)
            charts.extend(result.charts)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_use.id,
                "content": self._tool_result_text(result), "is_error": not result.ok,
            }]})

    # Session id used by _code_loop's sandbox calls; bound at the start of run().
    _session_id: str = ""
    _emit: EventFn = staticmethod(lambda t, p: None)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
