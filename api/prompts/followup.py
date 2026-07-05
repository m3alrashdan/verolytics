"""Follow-up Q&A prompt."""

FOLLOWUP_PROMPT = """The user asks a follow-up question about the dataset already analyzed in this
session:

<question>
{question}
</question>

Context: the data profile and a summary of previously computed results are below. The cleaned data
is at DATA_DIR + '/cleaned.parquet'.

<data_profile>
{profile_json}
</data_profile>

<previous_results_summary>
{results_summary}
</previous_results_summary>

Instructions:
- If answering needs computation, call execute_python (at most {max_steps} executions) and base your
  answer ONLY on the returned results. Never compute numbers yourself.
- If the question cannot be answered from this dataset, answer honestly that the data does not cover
  it — do not speculate.
- Answer in {language_name}, concisely. Every number in your answer must come from an execution
  result in this conversation (the prior results summary counts)."""


def followup_prompt(question: str, profile_json: str, results_summary: str,
                    max_steps: int, language: str) -> str:
    from api.prompts.system import LANGUAGE_NAMES

    return FOLLOWUP_PROMPT.format(
        question=question,
        profile_json=profile_json,
        results_summary=results_summary,
        max_steps=max_steps,
        language_name=LANGUAGE_NAMES.get(language, "English"),
    )
