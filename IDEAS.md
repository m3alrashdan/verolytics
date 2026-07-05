# Ideas (out of MVP scope — parked here per the project rules)

- Container pool: keep N warm sandbox containers to shave the ~1s cold start.
- Prompt-cache the growing code-generation conversation with explicit breakpoints.
- Streaming progress: stream the agent's step narration to the UI via SSE/websocket.
- Schema memory: remember column-cleaning decisions per user across sessions.
- Multi-sheet XLSX: analyze all sheets and detect relationships (now: first sheet + note).
- Cross-file joins: upload two files and let the agent join them.
- Cost meter: track token usage per session and show an estimated cost in the UI.
- Verifier v2: locate each number's source (which table/scalar) and footnote it in the
  report — turning verification into citations.
- Anomaly alerts: scheduled re-runs on fresh data with diff-against-last-report.
- Next.js frontend with proper report-page routing and shareable links.
- Export to PowerPoint (python-pptx) for the findings deck.
- Per-session container (long-lived kernel) to support iterative Q&A without re-loading
  data each execution — needs an in-container supervisor with its own timeout logic.
