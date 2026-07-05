"""Sandbox security & behavior tests. Require Docker + the built sandbox image."""
from __future__ import annotations

import uuid

import pytest

from api.config import get_settings
from api.services.sandbox import SandboxExecutor

pytestmark = pytest.mark.sandbox


def _docker_ready() -> bool:
    try:
        ex = SandboxExecutor()
        ex.client.ping()
        ex.ensure_image()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_docker = pytest.mark.skipif(not _docker_ready(),
                                     reason="docker or sandbox image unavailable")


@pytest.fixture()
def session(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_root", tmp_path)
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", None)
    executor = SandboxExecutor(settings)
    sid = uuid.uuid4().hex
    executor.create_workspace(sid)
    yield executor, sid
    executor.destroy_workspace(sid)


@requires_docker
def test_successful_execution_with_results(session):
    executor, sid = session
    result = executor.execute(sid, """
import pandas as pd
df = pd.DataFrame({"x": [1, 2, 3]})
save_table("t", df)
save_value("total", int(df["x"].sum()))
print("hello from sandbox")
""")
    assert result.ok, result.error
    assert result.scalars["total"] == 6
    assert result.tables["t"]["n_rows_total"] == 3
    assert "hello from sandbox" in result.stdout


@requires_docker
def test_error_returns_traceback(session):
    executor, sid = session
    result = executor.execute(sid, "df = undefined_variable + 1")
    assert not result.ok
    assert "NameError" in (result.error or "")
    assert "undefined_variable" in (result.traceback or "")


@requires_docker
def test_blocked_imports(session):
    executor, sid = session
    for code in ("import os", "import subprocess", "import socket",
                 "from os import system"):
        result = executor.execute(sid, code)
        assert not result.ok, f"{code!r} should be blocked"
        assert "blocked" in (result.error or ""), result.error


@requires_docker
def test_allowed_imports_work(session):
    executor, sid = session
    result = executor.execute(sid, """
import statsmodels.api as sm
from sklearn.linear_model import LinearRegression
import scipy.stats
save_value("ok", True)
""")
    assert result.ok, result.error


@requires_docker
def test_no_network(session):
    executor, sid = session
    # socket is blocked at import; even via pandas there is no network namespace
    result = executor.execute(sid, """
df = pd.read_csv("https://example.com/data.csv")
""")
    assert not result.ok


@requires_docker
def test_timeout_kills_container(session):
    executor, sid = session
    result = executor.execute(sid, "while True:\n    pass", timeout_s=5)
    assert not result.ok
    assert "Timeout" in (result.error or "")


@requires_docker
def test_filesystem_isolation(session):
    executor, sid = session
    # root fs is read-only; only /workspace and /tmp are writable
    result = executor.execute(sid, """
with open("/etc/evil.txt", "w") as f:
    f.write("nope")
""")
    assert not result.ok


@requires_docker
def test_chart_saved(session):
    executor, sid = session
    result = executor.execute(sid, """
fig = px.bar(x=["a", "b"], y=[1, 2], title="t")
save_chart("demo", fig, title="Demo chart")
""")
    assert result.ok, result.error
    assert result.charts and result.charts[0].name == "demo"
    ws = executor.workspace(sid)
    assert (ws / result.charts[0].html_path).exists()
