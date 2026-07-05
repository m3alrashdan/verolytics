# Evaluation Results

Live run via OpenRouter's Anthropic-format gateway, model `anthropic/claude-sonnet-4.6`,
constrained settings (`LLM_MAX_TOKENS=2000`, `MAX_ANALYSIS_STEPS=3`) to fit the free-tier
credit allowance. The account's allowance was exhausted after the first dataset
(~$0.20/dataset at these settings); the remaining 14 are pending credits.

| dataset | status | steps done/planned | verifier | ground-truth hits | time (s) |
|---|---|---|---|---|---|
| 01_clean_sales.csv | _pending credits_ | | | | |
| 02_messy_cp1256.csv | _pending credits_ | | | | |
| 03_arabic_columns.csv | _pending credits_ | | | | |
| 04_large_120k.csv | _pending credits_ | | | | |
| 05_no_time_column.csv | _pending credits_ | | | | |
| 06_single_column.csv | _pending credits_ | | | | |
| 07_heavy_duplicates.csv | _pending credits_ | | | | |
| 08_mixed_dates.csv | _pending credits_ | | | | |
| 09_financial.csv | _pending credits_ | | | | |
| 10_hr.csv | _pending credits_ | | | | |
| 11_inventory.csv | _pending credits_ | | | | |
| 12_customers.csv | _pending credits_ | | | | |
| 13_outliers.csv | _pending credits_ | | | | |
| **14_minimal.csv** | **ok** | **3/3** | **PASS (85 numbers checked, 0 unmatched)** | 5/8 expected aggregates present | 135.0 |
| 15_multisheet.xlsx | _pending credits_ | | | | |

**1/1 attempted datasets completed successfully; number accuracy 100% on the attempt.**

## Notes on the scored run (14_minimal.csv)

- Full autonomous loop: plan → cleaning (logged) → 3 analysis steps → report → verification.
- The verifier traced all 85 numbers in the report narrative to sandbox execution results.
- Ground-truth recall 5/8: the agent computed 5 of the 8 pandas-precomputed aggregates;
  the other 3 (per-column extremes it didn't cite) were simply not part of its chosen
  analyses — not errors.

## Re-running

```bash
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python evaluation/run_eval.py        # direct Anthropic
# or via OpenRouter: set ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL in .env (needs credits)
```

With default settings (12 steps, 8K max tokens) budget roughly $0.5–1.0 per dataset on
Sonnet 4.6 — ~$10–15 for the full suite. Report HTML/JSON artifacts of successful runs
are written to `evaluation/results_raw/` (gitignored).

## What each column means

- **verifier** — the number-verification gate's outcome on the final report
  (PASS = every narrative number traced to sandbox results).
- **ground-truth hits** — independently computed pandas aggregates (sum/mean/min/max per
  numeric column in `expected/`) found among the agent's computed results.
