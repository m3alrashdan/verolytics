"""HTTP middleware: request IDs + access logging, security headers, rate limiting.

Kept dependency-free and self-contained so it works in any deployment. The rate
limiter is in-memory (per process); a multi-process deploy that needs a hard
guarantee should front this with a shared store (e.g. Redis) or a gateway.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.config import Settings

logger = logging.getLogger("api.access")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def install_middleware(app: FastAPI, settings: Settings) -> None:
    rate = max(0, settings.rate_limit_per_minute)
    # ip -> (window_start_monotonic, count); pruned when it grows large
    window: dict[str, tuple[float, int]] = {}

    @app.middleware("http")
    async def observe_secure_limit(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        path = request.url.path

        # --- rate limit (fixed 60s window per client IP; /health is exempt) ---
        if rate and path != "/health":
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            start, count = window.get(ip, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            count += 1
            window[ip] = (start, count)
            if len(window) > 10_000:  # bound memory from unique IPs
                window.clear()
            if count > rate:
                logger.warning("rate-limited ip=%s path=%s rid=%s", ip, path, rid)
                resp = JSONResponse({"detail": "Rate limit exceeded — slow down."}, status_code=429)
                resp.headers["Retry-After"] = str(int(60 - (now - start)) + 1)
                resp.headers["X-Request-ID"] = rid
                for k, v in _SECURITY_HEADERS.items():
                    resp.headers[k] = v
                return resp

        start_t = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error rid=%s %s %s", rid, request.method, path)
            raise
        dur_ms = (time.perf_counter() - start_t) * 1000
        response.headers["X-Request-ID"] = rid
        for k, v in _SECURITY_HEADERS.items():
            response.headers[k] = v
        logger.info("%s %s -> %s %.1fms rid=%s",
                    request.method, path, response.status_code, dur_ms, rid)
        return response
