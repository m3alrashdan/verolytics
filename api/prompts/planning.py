"""Planning prompt: profile -> structured cleaning + analysis plan."""

PLANNING_PROMPT = """Below is the profile of the uploaded dataset{goal_clause}.

<data_profile>
{profile_json}
</data_profile>

Design the analysis. Respond with ONLY a JSON object (no markdown fences, no prose) of this shape:

{{
  "cleaning_plan": ["short description of each cleaning action, with justification"],
  "analysis_steps": [
    {{"step_number": 1, "description": "...", "hypothesis": "the specific question or expected pattern this step tests", "rationale": "..."}}
  ]
}}

Think like a senior analyst building an argument, not a report generator: each step should TEST A
HYPOTHESIS and move toward a decision, not just restate the data.

Requirements:
- cleaning_plan: address what the profile actually shows (missing values, duplicates, mixed date
  formats, inconsistent text categories, outliers). If nothing needs cleaning, return a single
  "no cleaning required" entry explaining why.
- analysis_steps: at most {max_steps} steps. Each has a falsifiable `hypothesis`. Choose analyses
  that explain WHY, not just WHAT: descriptive statistics (prefer median/IQR for skewed data),
  group-by aggregations with shares and deltas, driver/correlation analysis, time trends, Pareto
  (80/20), anomaly detection. Report effect sizes and proportions (e.g. "X drives 64% of Y"), not
  just raw totals.
- Always include one step that computes 4-8 KPI values (with period-over-period change when a time
  column exists) saved via save_value.
- If the data has an entity dimension (customers, products, stores, ...) AND at least 3 numeric
  features, include ONE segmentation step: standardize features, run KMeans for k in 2..6, pick k
  by silhouette score (save_value("silhouette_scores", ...)), save a cluster-profile table
  (mean of each feature per cluster + cluster sizes) and a radar/bar chart comparing clusters.
- If a time column exists and the series has at least {forecast_min_points} points, the LAST step
  must be a forecast: fit Holt-Winters (statsmodels) AND Prophet, backtest both on the last 20% of
  the series, pick the lower-MAPE model, then forecast with a confidence interval and save the MAPE,
  the chosen model name, the forecast table and a chart with confidence bands.
- Every step must say what it will save (tables/values/charts)."""


def planning_prompt(profile_json: str, goal: str | None, max_steps: int, forecast_min_points: int) -> str:
    goal_clause = f'. The user\'s stated goal: "{goal}"' if goal else ""
    return PLANNING_PROMPT.format(
        profile_json=profile_json,
        goal_clause=goal_clause,
        max_steps=max_steps,
        forecast_min_points=forecast_min_points,
    )


CLEANING_PROMPT = """Now execute the cleaning plan as ONE code block by calling execute_python.

Requirements:
- Load the raw file using EXACTLY this line (do not invent any other filename or path):
      df = {raw_load}
- Apply each cleaning action. For EVERY action append an entry to a `cleaning_log` list:
  {{"action": ..., "column": ..., "before_count": ..., "after_count": ..., "justification": ...}}
  (before_count/after_count are the affected row or value counts measured in code).
- Never modify the raw file. Save the cleaned dataframe to DATA_DIR + '/cleaned.parquet'.
- Finish with: save_value("cleaning_log", cleaning_log) and
  save_value("cleaned_shape", {{"rows": len(df), "cols": df.shape[1]}}).
"""

def cleaning_prompt(filename: str) -> str:
    """Build the cleaning prompt with the exact, unambiguous raw-file load line.

    The raw upload is stored as ``DATA_DIR + '/raw' + <original extension>``
    (e.g. raw.csv / raw.xlsx) — never under its original name. Weaker models
    guess the path from the profile's filename, so we hand them the literal call.
    """
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ".csv"
    if suffix in (".xlsx", ".xls"):
        raw_load = f"pd.read_excel(DATA_DIR + '/raw{suffix}')"
    else:
        raw_load = f"pd.read_csv(DATA_DIR + '/raw{suffix}')"
    return CLEANING_PROMPT.format(raw_load=raw_load)


STEP_PROMPT = """Execute analysis step {step_number}: {description}
Hypothesis to test: {hypothesis}
(Rationale: {rationale})

Write the code and call execute_python. Load data from DATA_DIR + '/cleaned.parquet'. Beyond the
headline number, also compute the evidence that confirms or refutes the hypothesis (shares, deltas,
group differences, an effect size or a simple significance check where it makes sense). Save every
result you will later cite via save_table/save_value, and charts via save_chart."""

RETRY_PROMPT = """The code failed. Read the traceback in the tool result, fix the root cause, and call
execute_python again with corrected code. Do not repeat the same failing approach."""
