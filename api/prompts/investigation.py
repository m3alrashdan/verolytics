"""Anomaly-investigation prompts (the "Smart Data Detective")."""

ANOMALY_CANDIDATES_PROMPT = """Review the computed results below. Identify up to {max_anomalies}
anomalies worth a focused investigation (sudden spikes/drops, outlier periods, suspicious values).

<computed_results>
{results_json}
</computed_results>

Respond with ONLY a JSON array (possibly empty):
[{{"title": "short anomaly name", "context": "what was observed, where (which table/value)"}}]

Only include anomalies actually visible in the results. If nothing stands out, return []."""

INVESTIGATE_PROMPT = """Investigate this anomaly like a detective: {title}
Observed: {context}

Write ONE code block (call execute_python) that drills down:
- isolate the anomalous period/rows in the cleaned data;
- break the anomaly down by every available dimension (product, region, category, ...) and
  quantify each dimension's contribution (counts, sums, % of the anomaly);
- compare against the baseline (same metric excluding the anomaly, or surrounding periods);
- if a single entity/order/row explains most of it, surface that row;
- save everything needed for a narrative via save_table/save_value, and one chart via save_chart
  showing the anomaly in context.
Also save_value("{key}_classification_evidence", {{...}}) with whatever helps classify the anomaly
as: one_time_event, emerging_trend, seasonal_pattern, or data_error."""
