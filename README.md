# Verolytics

**Verified AI data analysis — every number traced to executed code.**

Verolytics replaces a human data analyst end-to-end: upload a raw CSV/XLSX file, and the
agent autonomously **profiles → cleans → analyzes → charts → reports → forecasts**, then
answers follow-up questions — in English or Arabic (full RTL). Its core guarantee is
trust: no figure is ever guessed, every number is backed by Python it actually ran.

## v2 highlights

- **Next.js dashboard** (`web/`, port 3000): animated drop zone with sample datasets,
  live analysis canvas (SSE timeline + typewriter code panel + chart previews fading in),
  KPI cards with count-up, fully interactive Plotly charts with type switching, anomaly
  cards with classification tags, segment cards, data-quality health gauge, cleaning-log
  timeline, slide-out chat drawer with suggested questions, dark mode, EN/AR with RTL,
  onboarding tour, toasts and (optional) confetti.
- **Smart Data Detective**: the agent picks anomalies out of its own results, drills
  down by every dimension in a focused sub-loop, and reports a verified narrative tagged
  as one-time event / emerging trend / seasonal pattern / data error.
- **Auto-segmentation**: KMeans + silhouette-selected k with LLM-named, human-readable
  segments and per-segment recommendations.
- **What-if scenario engine**: "What if prices rose 10%?" → empirical-distribution
  Monte Carlo (1000 iterations) in the sandbox → expected/best/worst + outcome histogram,
  inline in the chat drawer.
- **NL data transformations**: describe a transformation in plain language, preview
  before/after samples, confirm to apply (never overwrites without confirmation).
- **Cross-file intelligence**: attach a second file, get fuzzy join suggestions with
  confidence scores, confirm to merge.
- **Executive deck**: one click → PPTX (python-pptx) or reveal.js web slides, built
  deterministically from the verified report.
- **Live progress over SSE** (`/sessions/{id}/progress`) with a DB-backed, replayable
  event log.

**The core guarantee: every number in the report comes from Python code actually executed
in an isolated Docker sandbox.** The LLM plans, writes code, and interprets results — it
never computes a number. A final verification gate regex-extracts every number from the
report narrative and rejects the report if any number cannot be traced back to a sandbox
execution result.

## Architecture

```
[Streamlit UI]  ── upload / questions / EN⇄AR toggle
      │
      ▼
[FastAPI Backend] ──── [PostgreSQL / SQLite: sessions, reports, logs]
      │
      ▼
[Agent Orchestrator]   plan → write code → execute → interpret → verify
      │ prompts                  │ python code
      ▼                          ▼
[LLM API]                [Docker Sandbox]   network_mode=none · 1 GB / 1 CPU
   (tool calling)                │           read-only rootfs · 60 s timeout
                                 ▼           import allowlist
                   results: tables/scalars as JSON, Plotly charts
                                 │
                                 ▼
                  [Verification Gate] ── every number traced or report rejected
                                 │
                                 ▼
                  [HTML report (interactive) + PDF (WeasyPrint)]
```

### The agent loop

1. **Profile** (pandas, no LLM): types, missing %, duplicates, IQR outliers, encodings
   (UTF-8 / Windows-1256 / ISO-8859-1 auto-detected), candidate time columns.
2. **Plan** (LLM → JSON): cleaning plan + ≤12 analysis steps, each with a rationale.
3. **Clean** (LLM code → sandbox): every action logged
   `{action, column, before_count, after_count, justification}`; the raw file is never
   modified; cleaned data is saved to `cleaned.parquet`.
4. **Analyze**: per step the LLM calls the `execute_python` tool; failures feed the
   traceback back for a fix (max 3 attempts, then the step is skipped and noted).
5. **Forecast** (when a time column has ≥24 points): Holt-Winters *and* Prophet,
   backtested on the last 20%, best MAPE wins; confidence interval + explicit reliability
   statement are mandatory.
6. **Interpret** (LLM): writes the report from the structured results JSON only.
7. **Verify** (no LLM): every number in the narrative is matched against the results
   JSON (exact / display-rounding / percent / thousands conversions). Unverifiable
   numbers ⇒ regeneration (×3) ⇒ last-resort redaction. Nothing unverified is published.

## Quick start (local dev)

```bash
# 1. sandbox image (the only hard prerequisite besides Docker)
docker build -t data-analyst-sandbox:latest sandbox/

# 2. python env
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. configure
cp .env.example .env       # add your LLM key: OpenRouter / Anthropic / OpenAI-compatible / Ollama

# 4. run
.venv/bin/uvicorn api.main:app --reload &          # API on :8000
cd web && npm install && npm run dev               # v2 dashboard on :3000
# legacy Streamlit MVP: API_URL=http://localhost:8000 .venv/bin/streamlit run frontend/app.py
```

## Quick start (docker compose)

```bash
docker build -t data-analyst-sandbox:latest sandbox/
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_API_KEY / an OpenAI-compatible key
export WORKSPACES_HOST_DIR=$PWD/workspaces       # host path for sibling-container mounts
docker compose up --build
# UI: http://localhost:8501   API: http://localhost:8000/docs
```

## Tests

```bash
.venv/bin/pytest                       # all (sandbox tests need Docker + image)
.venv/bin/pytest -m "not sandbox"      # unit tests only: profiler, verifier, agent loop
```

Covered: sandbox security (blocked imports, no network, read-only fs, timeout kill,
memory cap), profiler (types, encodings incl. Windows-1256 + Arabic columns, XLSX,
edge cases), verifier (exact/rounded/percent/thousands matching, hallucination
rejection, redaction), agent loop (retries, skip-after-3, step cap, verification
regeneration) and a full-pipeline integration test against the real sandbox.

## Evaluation

15 synthetic-but-realistic datasets live in `evaluation/datasets/` (clean sales, messy
Windows-1256, Arabic column names, 120K rows, no time column, single column, 40%
duplicates, mixed date formats, financial, HR, inventory, customers, outliers, <50 rows,
multi-sheet XLSX) with pandas-computed ground truth in `evaluation/expected/`.

```bash
.venv/bin/python evaluation/make_datasets.py     # regenerate datasets
.venv/bin/python evaluation/run_eval.py   # writes results.md
```

The harness scores pipeline success, the verifier outcome, ground-truth aggregate
recall and wall time per dataset. See `evaluation/results.md`.

## Security model (sandbox)

| Layer      | Enforcement                                                                                                                                          |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Network    | `network_mode=none` — no internet, full stop                                                                                                      |
| Resources  | 1 GB RAM, 1 CPU, 128 pids, 60 s wall-clock kill                                                                                                      |
| Filesystem | read-only rootfs; only the per-session`/workspace` + a 128 MB tmpfs                                                                                |
| Privileges | non-root UID,`no-new-privileges`                                                                                                                   |
| Imports    | allowlist (pandas, numpy, scipy, statsmodels, prophet, plotly, sklearn, matplotlib, openpyxl + safe stdlib);`os`/`subprocess`/`socket` blocked |
| Lifecycle  | fresh container per execution; workspace wiped with the session                                                                                      |

No `exec()`/`eval()` ever runs in the API process.

## Language support

The report language (EN/AR) is a user toggle: narrative, KPI labels, chart titles,
recommendations and the UI all switch, with full RTL layout in Arabic
(`report/templates/report_ar.html`). Data columns in any language are handled
regardless of the report language.

## Repository layout

See the project tree in the spec; notable entry points:
`api/main.py` (FastAPI), `api/services/agent.py` (the loop),
`api/services/verifier.py` (the gate), `sandbox/executor.py` (in-container runner),
`frontend/app.py` (Streamlit), `evaluation/run_eval.py` (eval harness).

## Status / roadmap

- [X] Sandbox, profiler, agent loop, verifier, reports (EN/AR, HTML+PDF), Q&A, Streamlit UI, eval harness
- [ ] Scored evaluation run (needs an API key) → `evaluation/results.md`
- [ ] Live deployment (Railway/Render/VPS via `docker-compose.yml`)
- [ ] Demo GIF/video

- Parked ideas: see `IDEAS.md`. Design rationale: see `DECISIONS.md`.
