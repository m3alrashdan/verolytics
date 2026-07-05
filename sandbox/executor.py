"""Sandbox executor — runs untrusted, LLM-generated Python inside the container.

Invoked as the container entrypoint with a single argument: the job directory
(default ``/workspace/job``). It reads ``code.py`` from the job directory,
executes it with a guarded import hook and result-capture helpers, and writes
a structured ``result.json`` next to it.

Security model (defense in depth — the container itself is the hard boundary):
- The container runs with ``network_mode=none``, a non-root user, a read-only
  root filesystem and only ``/workspace`` mounted writable.
- On top of that, this script blocks imports made *directly by user code* of
  any module outside the allowlist (``os``, ``subprocess``, ``socket`` …).
  Library-internal imports are unaffected because the guard only fires for
  frames whose ``__name__`` is the sandbox module name.
"""
from __future__ import annotations

import builtins
import io
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

# Pre-import the heavy allowlisted libraries so their internal import
# machinery is cached in sys.modules before the guard is installed.
import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

SANDBOX_MODULE_NAME = "__sandbox__"

ALLOWED_IMPORTS = {
    # analysis libraries (allowlist from the project spec)
    "pandas", "numpy", "scipy", "statsmodels", "prophet", "plotly",
    "sklearn", "matplotlib", "openpyxl",
    # harmless stdlib needed for ordinary data wrangling
    "json", "math", "statistics", "datetime", "re", "itertools",
    "collections", "functools", "operator", "io", "random", "string",
    "textwrap", "decimal", "fractions", "time", "calendar", "unicodedata",
    "typing", "warnings", "copy", "bisect", "heapq", "dataclasses", "enum",
}

MAX_TABLE_ROWS = 200
MAX_STDOUT_CHARS = 20_000


def _install_import_guard() -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        caller = globals.get("__name__") if isinstance(globals, dict) else None
        if caller == SANDBOX_MODULE_NAME:
            root = name.split(".")[0]
            if root not in ALLOWED_IMPORTS:
                raise ImportError(
                    f"import of '{root}' is blocked in the sandbox; "
                    f"allowed: {sorted(ALLOWED_IMPORTS)}"
                )
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import


def _jsonable(value: Any) -> Any:
    """Convert numpy/pandas scalars and containers to JSON-serializable types."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        v = float(value)
        return None if np.isnan(v) or np.isinf(v) else v
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _table_payload(df: pd.DataFrame) -> dict[str, Any]:
    truncated = len(df) > MAX_TABLE_ROWS
    head = df.head(MAX_TABLE_ROWS)
    records = json.loads(head.to_json(orient="records", date_format="iso"))
    return {
        "columns": [str(c) for c in df.columns],
        "rows": records,
        "n_rows_total": int(len(df)),
        "truncated": truncated,
    }


def run_job(job_dir: Path) -> dict[str, Any]:
    workspace = job_dir.parent
    charts_dir = workspace / "charts"
    charts_dir.mkdir(exist_ok=True)

    code = (job_dir / "code.py").read_text(encoding="utf-8")

    tables: dict[str, Any] = {}
    scalars: dict[str, Any] = {}
    charts: list[dict[str, Any]] = []

    def save_table(name: str, df: pd.DataFrame) -> None:
        """Record a DataFrame result (truncated to MAX_TABLE_ROWS rows)."""
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df)
        tables[str(name)] = _table_payload(df.reset_index() if df.index.name or not df.index.equals(pd.RangeIndex(len(df))) else df)

    def save_value(name: str, value: Any) -> None:
        """Record a scalar / dict / list result."""
        scalars[str(name)] = _jsonable(value)

    def save_chart(name: str, fig: Any, title: str | None = None) -> None:
        """Persist a Plotly figure as an HTML snippet (+ PNG for the PDF report)."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))
        html_path = charts_dir / f"{safe}.html"
        fig.write_html(str(html_path), include_plotlyjs=False, full_html=False)
        # plotly figure JSON so web frontends can render it natively
        fig.write_json(str(charts_dir / f"{safe}.json"))
        png_path: str | None = None
        try:
            p = charts_dir / f"{safe}.png"
            fig.write_image(str(p), width=900, height=500, scale=2)
            png_path = f"charts/{safe}.png"
        except Exception:  # kaleido unavailable or failed — HTML still works
            png_path = None
        charts.append({
            "name": str(name),
            "title": title or str(name),
            "html_path": f"charts/{safe}.html",
            "json_path": f"charts/{safe}.json",
            "png_path": png_path,
        })

    exec_globals: dict[str, Any] = {
        "__name__": SANDBOX_MODULE_NAME,
        "__builtins__": builtins,
        "pd": pd, "np": np, "px": px, "go": go,
        "WORKSPACE": str(workspace),
        "DATA_DIR": str(workspace / "data"),
        "save_table": save_table,
        "save_value": save_value,
        "save_chart": save_chart,
    }

    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    started = time.monotonic()
    ok, error, tb = True, None, None
    try:
        compiled = compile(code, "<user_code>", "exec")
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, exec_globals)  # noqa: S102 — this is the sandbox's job
    except BaseException as exc:  # noqa: BLE001 — report everything, never crash
        ok = False
        error = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc(limit=20)

    return {
        "ok": ok,
        "error": error,
        "traceback": tb,
        "stdout": stdout_buf.getvalue()[:MAX_STDOUT_CHARS],
        "stderr": stderr_buf.getvalue()[:MAX_STDOUT_CHARS],
        "tables": tables,
        "scalars": scalars,
        "charts": charts,
        "duration_s": round(time.monotonic() - started, 3),
    }


def main() -> int:
    job_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/job")
    _install_import_guard()
    try:
        result = run_job(job_dir)
    except Exception as exc:  # noqa: BLE001 — executor-level failure
        result = {
            "ok": False,
            "error": f"executor failure: {type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=20),
            "stdout": "", "stderr": "",
            "tables": {}, "scalars": {}, "charts": [], "duration_s": 0.0,
        }
    (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
