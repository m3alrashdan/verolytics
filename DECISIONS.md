# Architecture & Design Decisions

## D1 — Model: `claude-sonnet-4-6` instead of `claude-sonnet-4-20250514`
The spec named `claude-sonnet-4-20250514`, which Anthropic deprecated with a retirement
date of **2026-06-15** (four days after this project started). `claude-sonnet-4-6` is the
official drop-in replacement. The model is configurable via `ANTHROPIC_MODEL`.

## D2 — Fresh container per execution, persistent workspace per session
The spec says "separate Docker container per session". We go slightly stricter: a fresh
container per *execution*, all mounting the same per-session workspace. Rationale:
- a hard wall-clock timeout is trivially enforceable (`container.wait(timeout)` + kill);
- a crashed/OOM-killed execution cannot poison later steps;
- state between steps flows through files (`data/cleaned.parquet`, `charts/*`), which is
  also what makes follow-up Q&A and retries reproducible.
Container startup overhead (~1s) is negligible next to LLM latency.

## D3 — Import allowlist enforced *inside* the container, container as the real boundary
The executor blocks non-allowlisted imports only for frames belonging to user code, so
library internals (sklearn importing `os`) still work. This is a tripwire, not the
security boundary — the boundary is the container itself: `network_mode=none`, non-root
UID, read-only rootfs, 1 GB / 1 CPU / 128 pids caps, only `/workspace` writable.

## D4 — Verifier: small-integer exemption and unit conversions
Strict "every token must match" produces false rejections for ordinals and counts the
narrative naturally produces ("top 3 products", "step 2"). Rules:
- integers 0–12 are exempt (structural numbers, not analytical claims);
- a number matches if a results value equals it exactly, after rounding to the displayed
  precision, or via percent (0.124 → 12.4%) / thousands (50000 → 50K) conversion;
- numbers inside result *strings* (dates "2024-01-31", labels) count as results, so years
  and months are citable.
Anything else is rejected.

## D5 — Verification failure: regenerate ×3, then redact (never publish, never crash)
The spec demands rejection + regeneration but also "never crash the whole pipeline".
After `MAX_VERIFICATION_ATTEMPTS` failed regenerations we *redact* the offending numbers
(replaced with `[unverified]`) and flag the report visibly. A hallucinated number can
therefore never reach the reader, and the user still gets the verified remainder.

## D6 — One forced-tool-call conversation for code generation
Code generation uses native tool calling with `tool_choice` forced to `execute_python` —
no string-parsing of markdown code fences. Planning and interpretation are separate
plain-JSON calls so the report writer sees *only* the structured results, not the code
conversation (smaller context, less anchoring).

## D7 — Interpretation input == verification input
The exact results JSON given to the report-writing prompt is the same object the verifier
collects candidate numbers from. There is no second source of truth.

## D8 — SQLite by default, Postgres in compose
`DATABASE_URL` switches between them; session state and reports are stored as JSON
columns (schema churn is high during development, queries are by primary key only).

## D9 — Streamlit first
Spec-sanctioned: Streamlit for the MVP, Next.js later. The frontend only talks to the
FastAPI backend, so the swap is isolated.

## D11 — v2 web frontend: lightweight i18n instead of next-intl
The v2 spec listed next-intl. With exactly two locales and no locale routing
requirement, a zustand-persisted `lang` + typed dictionary (`web/lib/i18n.ts`) delivers
the same EN/AR + RTL behavior with far less machinery (no middleware, no per-locale
routes). Swapping to next-intl later is localized to `lib/i18n.ts` call sites.

## D12 — Executive deck is built deterministically from the verified report
The spec suggested the LLM picks "slide-worthy" findings. Slides are instead distilled
in code from the already-verified report (title → KPIs → top findings → segments →
anomalies → forecast → recommendations → appendix). This adds zero new hallucination
surface — every number on a slide already passed the verification gate — and works
without an extra LLM call.

## D13 — SSE progress via DB-backed event log
Progress events are appended to an `events` table and the SSE endpoint tails it.
This survives multi-worker deployments and reconnects (the stream replays history
before tailing), unlike an in-memory queue. Polling interval is 0.5 s — well under
perception threshold for a progress UI.

## D14 — What-if scenarios are sandbox Monte Carlo, chat-integrated
Scenario questions ("What if …") run through the same execute-verify loop as
everything else: the model derives empirical distributions from the actual data,
runs 1000 Monte Carlo iterations in the sandbox, and only result numbers reach the
answer. The chat drawer routes "What if/ماذا لو" questions to the scenario endpoint
automatically.

## D10 — Parquet for the cleaned-data handoff
`data/cleaned.parquet` preserves dtypes (especially parsed datetimes) across the
stateless executions; CSV would re-introduce date-parsing drift between steps. pyarrow
was added to the sandbox image for this.
