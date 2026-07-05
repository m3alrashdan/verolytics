"""Report-writing prompt: structured results -> report JSON."""

INTERPRETATION_PROMPT = """All analysis steps are complete. Below are the COMPUTED RESULTS from the
sandbox. Write the final report in {language_name}.

<computed_results>
{results_json}
</computed_results>

<available_charts>
{charts_json}
</available_charts>

CRITICAL RULES — the report is machine-verified and will be REJECTED if violated:
- Use ONLY the numbers from the results above. Do not invent, estimate, recompute or extrapolate
  any number. Do not round differently than shown (citing a results value with fewer decimals is
  allowed; adding precision is not).
- Every KPI value, every number in every narrative, and every number in the recommendations must
  appear in the results.
- If the results do not support a claim, do not make the claim.

Respond with ONLY a JSON object (no markdown fences) of this shape:
{{
  "title": "...",
  "executive_summary": "3-6 sentences, the most decision-relevant facts",
  "kpis": [{{"label": "...", "value": "...", "change": "+12.4%" or null, "change_direction": "up|down|flat" or null}}],
  "findings": [{{"title": "...", "narrative": "2-5 sentences interpreting the result, citing its numbers", "chart_name": "name of a chart from available_charts or null"}}],
  "data_quality_notes": "short paragraph on data quality and the impact of cleaning",
  "forecast": null or {{"narrative": "...", "model_name": "Holt-Winters|Prophet", "mape": <number from results>, "chart_name": "..." or null, "reliability_statement": "explicit statement on how reliable this forecast is, citing the MAPE"}},
  "anomalies": [{{"title": "...", "narrative": "detective-style narrative: what spiked/dropped, which dimensions explain it and by how much, what the metric looks like excluding it — all numbers from results", "tag": "one_time_event|emerging_trend|seasonal_pattern|data_error", "chart_name": "..." or null}}],
  "segments": [{{"name": "human-readable segment label (e.g. 'High-Value Loyal Customers')", "description": "what characterizes this cluster, citing its profile numbers", "recommendation": "one actionable recommendation for this segment"}}],
  "recommendations": ["numbered, actionable recommendation grounded in a cited finding", ...]
}}

- 4-8 KPIs. 3-7 findings, each tied to a chart when one exists. 3-6 recommendations.
- Every finding must pass the "so what?" test: state the magnitude (share/delta, not just a raw
  number), then why it matters for a decision. No filler findings that merely restate a total.
- Recommendations must be specific and tied to a cited finding (what to do, for whom, expected effect)
  — not generic advice like "monitor the data".
- anomalies: [] unless anomaly-investigation results exist — then one entry per investigated
  anomaly. segments: [] unless a clustering/segmentation step ran — then one entry per cluster.
- Write all text (labels, titles, narratives, recommendations) in {language_name}.
- If a forecast step ran, the forecast section is MANDATORY and must include mape and
  reliability_statement. A forecast without a confidence statement is forbidden."""


CRITIQUE_PROMPT = """You are a skeptical senior analyst reviewing a junior's DRAFT report before it
ships. You have the COMPUTED RESULTS (the only source of truth) and the draft.

<computed_results>
{results_json}
</computed_results>

<draft_report>
{report_json}
</draft_report>

Audit the draft hard for: (1) claims not supported by the results, (2) shallow findings that just
restate a total without a "so what", (3) numbers stated with more precision than the results,
(4) weak/generic recommendations, (5) obvious insights the results clearly support but the draft
omitted (e.g. a dominant driver, a concentration/Pareto effect, a notable group gap).

Respond with ONLY a JSON object (no markdown fences):
{{
  "verdict": "accept" | "revise",
  "issues": [{{"severity": "high|medium|low", "area": "summary|finding|kpi|recommendation|forecast|anomaly|segment", "problem": "what is wrong", "fix": "concrete fix using only results numbers"}}],
  "missing_insights": ["an insight the results support but the draft omitted, phrased as the finding to add"]
}}

Be strict but fair: return "accept" with empty arrays only if the draft is genuinely sound."""


REVISION_PROMPT = """Revise your report to address this review. Apply every high- and medium-severity
fix and add the missing insights — using ONLY numbers that appear in the computed results (same
rounding or coarser). Keep everything that was already correct.

<computed_results>
{results_json}
</computed_results>

<your_previous_report>
{report_json}
</your_previous_report>

<review>
{critique_json}
</review>

Respond with ONLY the corrected, complete report JSON in the same shape as before, written in
{language_name}."""

EMPTY_REPORT_REPROMPT = """Your report had no findings and no KPIs, but the computed results below
clearly contain analyzable numbers. That is not acceptable. Produce a COMPLETE report now: at least
3 findings (each citing numbers from the results and passing the "so what?" test) and 4-8 KPIs.

<computed_results>
{results_json}
</computed_results>

<available_charts>
{charts_json}
</available_charts>

Respond with ONLY the full report JSON in the required shape, written in {language_name}. Use ONLY
numbers that appear in the results."""


VERIFICATION_FAILURE_PROMPT = """VERIFICATION FAILED. These numbers in your report could not be traced
to the computed results: {unmatched}.

Rewrite the report JSON. Remove or replace every untraceable number — use only numbers that appear
verbatim in the computed results (same rounding or coarser). Respond with ONLY the corrected JSON."""


def interpretation_prompt(results_json: str, charts_json: str, language: str) -> str:
    from api.prompts.system import LANGUAGE_NAMES

    return INTERPRETATION_PROMPT.format(
        results_json=results_json,
        charts_json=charts_json,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
