"""Docker sandbox manager.

Every code execution runs in a fresh, throwaway container created from the
pre-built sandbox image:

- ``network_mode="none"``        — no internet, ever
- 1 GB memory / 1 CPU / 128 pids — resource caps
- read-only root filesystem      — only ``/workspace`` (the per-session
  directory) is writable, plus a small tmpfs on ``/tmp``
- hard wall-clock timeout        — the container is killed if it exceeds it

State between steps is carried through files in the session workspace
(``data/`` for datasets, ``charts/`` for chart artifacts), so each execution
is otherwise stateless.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path

import docker
from docker.errors import ImageNotFound

from api.config import Settings, get_settings
from api.models.session import ExecutionResult

logger = logging.getLogger(__name__)

# Process-wide cap on concurrent containers (see Settings.max_concurrent_sandboxes).
# Created lazily on first use so the limit is read from settings.
_run_semaphore: threading.BoundedSemaphore | None = None
_sem_lock = threading.Lock()


def _acquire_slot(limit: int) -> threading.BoundedSemaphore:
    global _run_semaphore
    if _run_semaphore is None:
        with _sem_lock:
            if _run_semaphore is None:
                _run_semaphore = threading.BoundedSemaphore(max(1, limit))
    _run_semaphore.acquire()
    return _run_semaphore


class SandboxError(RuntimeError):
    """Raised when the sandbox infrastructure itself fails (not user code)."""


class SandboxExecutor:
    """Creates per-session workspaces and runs code in isolated containers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: docker.DockerClient | None = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def ensure_image(self) -> None:
        try:
            self.client.images.get(self.settings.sandbox_image)
        except ImageNotFound as exc:
            raise SandboxError(
                f"sandbox image '{self.settings.sandbox_image}' not found — "
                "build it with: docker build -t data-analyst-sandbox:latest sandbox/"
            ) from exc

    # -- workspace management -------------------------------------------------

    def create_workspace(self, session_id: str) -> Path:
        ws = self.settings.workspace_root.resolve() / session_id
        for sub in ("data", "job", "charts"):
            (ws / sub).mkdir(parents=True, exist_ok=True)
        return ws

    def workspace(self, session_id: str) -> Path:
        return self.settings.workspace_root.resolve() / session_id

    def destroy_workspace(self, session_id: str) -> None:
        ws = self.workspace(session_id)
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    # -- execution -------------------------------------------------------------

    def execute(self, session_id: str, code: str, timeout_s: int | None = None) -> ExecutionResult:
        """Run ``code`` in a fresh container against the session workspace."""
        timeout_s = timeout_s or self.settings.sandbox_timeout_s
        ws = self.workspace(session_id)
        job_dir = ws / "job"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "code.py").write_text(code, encoding="utf-8")
        result_file = job_dir / "result.json"
        result_file.unlink(missing_ok=True)

        host_ws = self.settings.host_workspace(session_id)
        # Run as the workspace owner so the executor can write result.json.
        # When the API runs as root (e.g. in a container), hand the workspace
        # to the image's unprivileged user instead of running the sandbox as root.
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            uid = gid = 1001
            for p in [ws, *ws.rglob("*")]:
                os.chown(p, uid, gid)
        name = f"sbx-{session_id[:8]}-{uuid.uuid4().hex[:8]}"
        logger.info("sandbox run session=%s container=%s timeout=%ss", session_id, name, timeout_s)

        # Bound concurrent containers so parallel analyses can't exhaust the host.
        sem = _acquire_slot(self.settings.max_concurrent_sandboxes)
        container = None
        try:
            container = self.client.containers.run(
                self.settings.sandbox_image,
                command=["/workspace/job"],
                name=name,
                detach=True,
                network_mode="none",
                mem_limit=self.settings.sandbox_mem_limit,
                nano_cpus=self.settings.sandbox_nano_cpus,
                pids_limit=128,
                read_only=True,
                tmpfs={"/tmp": "rw,size=128m"},
                volumes={str(host_ws): {"bind": "/workspace", "mode": "rw"}},
                security_opt=["no-new-privileges"],
                user=f"{uid}:{gid}",
                environment={"HOME": "/tmp", "MPLCONFIGDIR": "/tmp"},
            )
            try:
                exit_info = container.wait(timeout=timeout_s)
            except Exception:  # requests.exceptions timeout — wall clock exceeded
                container.kill()
                logger.warning("sandbox timeout session=%s after %ss", session_id, timeout_s)
                return ExecutionResult(
                    ok=False,
                    error=f"TimeoutError: execution exceeded {timeout_s}s and was killed",
                )
            if result_file.exists():
                payload = json.loads(result_file.read_text(encoding="utf-8"))
                return ExecutionResult.model_validate(payload)
            # No result file: the executor crashed hard (e.g. OOM-killed)
            logs = container.logs(tail=50).decode("utf-8", errors="replace")
            status = exit_info.get("StatusCode")
            err = "MemoryError: execution exceeded the sandbox memory limit" if status == 137 \
                else f"sandbox exited with status {status} and produced no result"
            return ExecutionResult(ok=False, error=err, stderr=logs[:5000])
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001 — cleanup is best-effort
                    logger.exception("failed to remove container %s", name)
            sem.release()
