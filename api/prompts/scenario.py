"""What-if scenario and natural-language transformation prompts."""

SCENARIO_PROMPT = """The user asks a what-if scenario question about the analyzed dataset:

<scenario>
{description}
</scenario>

Context — data profile and previously computed results:
<data_profile>
{profile_json}
</data_profile>
<previous_results_summary>
{results_summary}
</previous_results_summary>

Build a simulation grounded in the ACTUAL data (DATA_DIR + '/cleaned.parquet') — never invent
distributions. Call execute_python with code that:
1. Identifies the variables the scenario modifies and derives their empirical distributions /
   relationships from the data itself (e.g. bootstrap resampling, observed elasticities).
2. Runs a Monte Carlo simulation with {n_iterations} iterations.
3. Saves via save_value: "expected_outcome", "best_case" (p95), "worst_case" (p5),
   "baseline" (current value for comparison), and any intermediate facts you will cite.
4. Saves a histogram of simulated outcomes via save_chart("scenario_distribution", fig).

After the execution result returns, answer in {language_name}: the projected impact vs the
baseline, the confidence range (p5–p95), and the key assumption the simulation makes. Use ONLY
numbers from the execution results. If the data cannot support this scenario, say so honestly."""

TRANSFORM_PROMPT = """The user wants to transform the dataset using this plain-language instruction:

<instruction>
{instruction}
</instruction>

Data profile:
<data_profile>
{profile_json}
</data_profile>

Call execute_python with code that:
1. Loads DATA_DIR + '/cleaned.parquet' (fall back to the raw file if it does not exist).
2. Applies the transformation EXACTLY as described. Do not change anything else.
3. Saves the result to DATA_DIR + '/transformed.parquet' (do NOT overwrite cleaned.parquet).
4. Saves a preview: save_table("before_sample", <5 affected rows before>),
   save_table("after_sample", <the same 5 rows after>),
   save_value("transform_summary", {{"rows_affected": ..., "rows_total": ...,
   "columns_added": [...], "columns_removed": [...], "description": "one-line summary"}}).

After the result returns, reply in {language_name} with one short sentence describing what the
transformation did (cite rows_affected from the result). If the instruction is ambiguous or
impossible for this data, do not transform — explain what is unclear."""
