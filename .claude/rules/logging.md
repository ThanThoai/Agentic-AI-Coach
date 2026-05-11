# Logging & exception logging rules

Structured logging is part of the API contract — operators read logs the way users read your responses. These rules apply to every service in this project, with extra emphasis on **exception logging** (where most of the bugs in log pipelines live).

## Stack

- **structlog** with JSON renderer in prod, console renderer in dev (toggle via `settings.env`).
- Wired in `app/main.py` lifespan, **once**. No `logging.basicConfig()` elsewhere.
- Errors also forwarded to a tracker (Sentry / OTLP) when `settings.error_tracking_dsn` is set.

## 1. The seven fields every log line must have

Every log line — info, warning, error — carries these structured fields:

| Field          | Why                                                       |
|----------------|-----------------------------------------------------------|
| `timestamp`    | UTC, ISO-8601, ms precision (auto-added by structlog)     |
| `level`        | `info` / `warning` / `error` / `critical`                 |
| `logger`       | Module name (`app.api.users`, `app.deployments.llm`)      |
| `event`        | A short, **stable** English noun-phrase (`user.login.failed`, not `"User john failed login"`) — this is the searchable key |
| `request_id`   | Per-request UUID set by middleware; propagated everywhere |
| `principal_id` | Authenticated user / api-key id (omit for anonymous)      |
| `service`      | `api`, `serve-replica`, `worker` — distinguishes processes |

Variables go in extra fields, not the message: `log.info("user.login.failed", reason="bad_password", attempt=3)` — never `log.info(f"login failed for {user} reason={reason}")`.

## 2. Log levels — when to use which

| Level      | Use for                                                                                  | Don't use for                                       |
|------------|------------------------------------------------------------------------------------------|-----------------------------------------------------|
| `debug`    | Per-request detail in dev; off in prod by default                                        | Anything you want to see in prod                    |
| `info`     | Lifecycle (startup/shutdown), business events (order placed, model loaded), 2xx requests | Rare events, errors                                 |
| `warning`  | Recoverable issue (retry succeeded, fallback path taken, deprecation hit, slow query)    | Anything that needs human action this week          |
| `error`    | Request failed (5xx), exception caught at the boundary, external dependency down         | Validation 4xx, expected business rejections        |
| `critical` | Service-level failure (DB pool exhausted, deployment unhealthy across all replicas)      | Anything routine; reserve for "page someone now"    |

**4xx is `info` (or `warning` if anomalous), not `error`.** A user typo'd a request — that's not your bug. Errors are *your* errors.

`401` rate spikes go to **metrics + alert**, not to `error` logs (otherwise a bot drowns the log).

## 3. Exception logging — the right shape

### 3a. The single rule

When an exception is caught and the request fails: log **once**, at the boundary, with **`exc_info=True`** (structlog: `log.exception(...)` or `log.error(..., exc_info=True)`):

```python
log.exception(
    "request.failed",
    method=request.method,
    path=request.url.path,
    status=500,
    elapsed_ms=elapsed,
    err_type=type(exc).__name__,
)
```

Don't:
- Log + re-raise + log again (duplicate stack traces).
- Log only `str(exc)` (loses the traceback).
- Log the exception in a deep helper, then catch and re-raise; the boundary will log too.

### 3b. The boundary is the FastAPI exception handler

```python
# app/core/exceptions.py
import structlog
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


def install(app: FastAPI) -> None:

    @app.exception_handler(HTTPException)
    async def http_exc(req: Request, exc: HTTPException):
        # Client error (4xx): info; server error (5xx): error.
        lvl = log.error if exc.status_code >= 500 else log.info
        lvl(
            "request.http_exception",
            method=req.method, path=req.url.path,
            status=exc.status_code, code=exc.detail if isinstance(exc.detail, str) else None,
        )
        return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail)}}, status_code=exc.status_code)

    @app.exception_handler(DomainError)
    async def domain_exc(req: Request, exc: "DomainError"):
        log.warning(
            "request.domain_error",
            method=req.method, path=req.url.path,
            err_type=type(exc).__name__, code=exc.code,
        )
        return JSONResponse(exc.to_response(), status_code=exc.status)

    @app.exception_handler(Exception)
    async def unhandled(req: Request, exc: Exception):
        # Last resort. Always log with exc_info; never expose traceback to client.
        log.exception(
            "request.unhandled",
            method=req.method, path=req.url.path,
            err_type=type(exc).__name__,
        )
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Internal server error",
                       "request_id": getattr(req.state, "request_id", None)}},
            status_code=500,
        )
```

Routes raise. They **never** catch + format. The handler is the one place a stack trace touches the log.

### 3c. The exception body in a log line

Always include:

- `err_type` (class name) — so dashboards can group.
- `err_code` — your stable string code if it's a domain exception (`payment.declined`, `model.timeout`).
- `err_msg` — `str(exc)` short, **scrubbed of PII/secrets** (see §6). Truncate to ~500 chars.
- The full traceback via `exc_info=True` — structlog formats it as a separate `exception` field, not concatenated into the message.
- For `__cause__` / `__context__`, structlog preserves the chain.

Don't include:

- `repr(exc)` of large objects (DB row, ORM model) — they may dump fields including secrets.
- The full request body unless it's already in the redaction allowlist for that route.

### 3d. Domain exceptions

Define a small hierarchy:

```python
# app/core/exceptions.py

class DomainError(Exception):
    code: str = "domain_error"
    status: int = 400
    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}
    def to_response(self) -> dict:
        return {"error": {"code": self.code, "message": str(self), "details": self.details}}

class NotFoundError(DomainError):
    code, status = "not_found", 404

class ConflictError(DomainError):
    code, status = "conflict", 409

class ModelTimeoutError(DomainError):
    code, status = "model_timeout", 504

class RateLimitedError(DomainError):
    code, status = "rate_limited", 429
```

Routes raise `NotFoundError("user.not_found")`; the handler maps to status + JSON; the log line gets `err_code=not_found`. Stable code → stable dashboards → stable alerts.

## 4. What to log per request — the access log

Every completed request emits one **access log** line at the end (middleware):

```python
log.info(
    "request.completed",
    method=req.method, path=req.url.path, status=response.status_code,
    elapsed_ms=elapsed, principal_id=principal_id,
    user_agent=req.headers.get("user-agent"),
    client_ip=req.client.host,           # respect ProxyHeadersMiddleware
    bytes_in=int(req.headers.get("content-length", 0)),
    bytes_out=getattr(response, "_body_size", None),
)
```

- One line per request. Don't log `request.started` — it's noise; you can derive it from `completed`.
- The request body is **not** in the access log. Ever. Use a separate audit channel for that.

## 5. Async-specific rules (this is where most logs go wrong)

### 5a. Never log `asyncio.CancelledError` as ERROR

When the client disconnects, FastAPI raises `CancelledError` inside the handler. That's normal, not a bug:

```python
try:
    result = await do_work()
except asyncio.CancelledError:
    log.info("request.cancelled", path=req.url.path)
    raise                    # propagate so the framework can clean up
except Exception:
    log.exception("request.failed", ...)
    raise
```

If you `except Exception:` without re-raising `CancelledError` first, you turn cancellation into a 500 error storm. **Catch `CancelledError` separately, log at info, re-raise.**

### 5b. Background tasks die silently

`fastapi.BackgroundTasks` and `asyncio.create_task(coro)` swallow exceptions if you don't add a done-callback. Wrap every fire-and-forget:

```python
def _log_task_error(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("background.failed", task=task.get_name())

t = asyncio.create_task(coro, name="user.welcome_email")
t.add_done_callback(_log_task_error)
```

For real durability, use a job queue (Arq/Celery/RQ) — `BackgroundTasks` is for low-stakes side-effects only.

### 5c. Streaming responses — log at end, not at start

You've sent `200 OK` and headers — the request didn't fail until the stream ends. Log once when the generator exits (success or error):

```python
async def gen():
    started = monotonic()
    sent = 0
    try:
        async for chunk in upstream:
            sent += len(chunk)
            yield chunk
    except asyncio.CancelledError:
        log.info("stream.cancelled", path=path, sent_bytes=sent, elapsed_ms=int((monotonic()-started)*1000))
        raise
    except Exception:
        log.exception("stream.failed", path=path, sent_bytes=sent)
        # send an error event into the stream (see streaming.md), then return
        yield error_event
    else:
        log.info("stream.completed", path=path, sent_bytes=sent, elapsed_ms=int((monotonic()-started)*1000))
```

A failed stream is **still a 200** to access logs — the failure shows up in `stream.failed`, not in the access log status code. Build dashboards on `event=stream.*`.

### 5d. `try/finally` is not for logging

Don't put `log.info(...)` in `finally:` — it runs on `CancelledError` too, and you'll get duplicates. Use `else:` for the success path, explicit `except` for error paths.

## 6. Redaction — what must never appear in logs

A blocklist (apply via a structlog processor at the root logger):

- Passwords, tokens (`authorization`, `cookie`, `set-cookie` headers).
- API keys (any field whose name matches `*_token`, `*_key`, `*_secret`, `password`, `passwd`, `pwd`).
- Credit card numbers (Luhn-pass) and CCV.
- National IDs (SSN/CCCD/MyKad), full DoB.
- Full email or phone unless the route's audit policy whitelists it (then log a hash or last-4).
- Request bodies of auth routes (`/login`, `/register`, `/reset`, `/oauth/*`).
- LLM system prompts (extractable via injection — keep them out of logs).

Redaction processor sketch:

```python
SECRET_KEYS = {"password","passwd","pwd","token","secret","authorization","cookie","api_key","jwt","hf_token","openai_api_key"}

def redact(_, __, event_dict):
    def _walk(o):
        if isinstance(o, dict):
            return {k: ("***REDACTED***" if k.lower() in SECRET_KEYS else _walk(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [_walk(x) for x in o]
        return o
    return _walk(event_dict)
```

**Never** trust upstream not to leak — apply redaction at the logger, not at every call site. Defense in depth.

## 7. Correlation — `request_id` everywhere

A middleware generates `request_id` (use `X-Request-Id` from upstream if present and trusted), stores on `request.state.request_id`, and binds it to the structlog context:

```python
import contextvars, uuid, structlog
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response
        finally:
            request_id_var.reset(token)
```

structlog reads `request_id_var` via a processor, so every `log.*(...)` call inside the request automatically carries it — no plumbing in the routes.

For **Ray Serve**: pass `request_id` through to the deployment in the payload, and re-bind it in the deployment's logger context. Otherwise the replica's logs are uncorrelatable to the API's logs.

## 8. External dependency errors

When an outbound call fails (HTTP, DB, model handle):

- Log at the call site **only if you handle it locally** (retry, fallback). Then the log line stays at `warning` (`db.retry`, `http.fallback`).
- Log at the boundary if it propagates. Don't log twice.
- Always include: dependency name, operation, elapsed_ms, attempt #, the full upstream error code/status.

Example (httpx with retry):

```python
for attempt in range(1, 4):
    try:
        r = await client.post(url, json=body, timeout=5.0)
        r.raise_for_status()
        return r.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
        if attempt == 3:
            log.warning("http.upstream.failed", url=url, attempt=attempt, err_type=type(e).__name__, status=getattr(getattr(e, "response", None), "status_code", None))
            raise
        log.info("http.upstream.retry", url=url, attempt=attempt, err_type=type(e).__name__)
        await asyncio.sleep(0.2 * 2**attempt)
```

For Ray Serve `DeploymentHandle`:

- `RayServeException` → log + 502.
- Replica restart mid-request → log `serve.replica.restarted` + retry once.
- Don't log every `RayActorError` as `critical` — it's expected during scale-down. Use `warning` and rely on metrics.

## 9. Database errors (deserve their own treatment)

- `IntegrityError` (unique constraint, FK violation) is usually a 4xx domain condition (duplicate). Catch in the service layer, raise `ConflictError` — log at `info`. If it's unexpected, log at `error`.
- `OperationalError` (connection lost, deadlock) → `error`. Retry once for deadlocks (`40P01`), don't retry for everything else blindly.
- `DataError` (bad value for column) → `error` and a 500. This is your bug — the type system should have caught it.
- **Never log SQL with parameters** — params can be PII. If you need the SQL, log the parameterized statement only (`SELECT * FROM users WHERE id = $1`). For slow-query log, hash the params.

## 10. Sampling and rate-limiting log spam

- A single bad client can push 1000 stack traces / second. The log pipeline costs money; the signal drowns.
- Use a **dedup window** for repeated identical exception types per principal: log first 5 within a minute at `error`, then summarize ("100 more `model_timeout` from principal X in last 60s").
- For very high-volume info logs (per-token streaming), sample (1 in N) and emit a periodic summary instead.
- Sentry / Datadog clients have built-in dedup — verify it's enabled.

## 11. Logging in Ray Serve replicas

- One logger per process. `RAY_DEDUP_LOGS=0` is set in `settings.json` so per-replica logs aren't merged in misleading ways.
- Replica logs include the deployment name + replica id (Ray injects these in the log handler).
- For request-scoped fields, push `request_id` in via the payload and bind in the deployment:
  ```python
  async def __call__(self, payload):
      with structlog.contextvars.bound_contextvars(request_id=payload.get("request_id"), deployment="llm"):
          ...
  ```
- Replica startup/shutdown lifecycle goes to `info`. Model load is `info` with `elapsed_ms`. Health-check failures are `warning` once, `error` on the third consecutive miss.

## 12. Logging for security events

These are **distinct** from request logs and may go to a different sink (SIEM):

- `auth.login.success` / `auth.login.failed` (with `reason` — `bad_password`, `mfa_required`, `account_locked`).
- `auth.token.issued` / `auth.token.revoked`.
- `authz.denied` (principal tried to access something they shouldn't).
- `secret.access` (high-value secret read; correlated with operational changes).
- `admin.action` (any privileged write).

Tag with `category=security` so SIEM filters work. Never include the secret itself; include identifiers (key id, role, target).

## 13. What goes to traces vs logs

- **Logs**: discrete events ("X happened at T with these fields").
- **Traces**: hierarchical timing of work (spans, parent-child).
- **Metrics**: aggregated counters/histograms (rates, latency distribution).

Don't try to reconstruct traces from logs. If you find yourself logging "step 1 started… step 1 finished… step 2 started…", switch to OpenTelemetry spans.

Logs reference traces via `trace_id` / `span_id` if OTel is wired — add them to the structlog context the same way as `request_id`.

## 14. What goes to error tracking (Sentry / GlitchTip / OTLP)

- Every `error` and `critical` log line is forwarded.
- Include the full exception with `exc_info=True` (Sentry's structlog integration handles this).
- Tag with `release` (git SHA), `environment` (`prod`/`staging`), `service` (`api`/`serve-replica`).
- Set user context to `principal_id` (not raw email).
- **Don't** forward 4xx domain errors. Filter out `DomainError` subclasses with status < 500.
- Set `before_send` to drop high-frequency known-noise events.

## 15. Acceptance checklist for any new route / deployment

Before merging code that adds a route or deployment, verify:

- [ ] Routes never `try/except Exception` then format JSON — the handler does it.
- [ ] Domain exceptions used for known business failures; raised, not logged at the call site.
- [ ] Access log is emitted for the new route (middleware handles it; no work needed unless the route bypasses the framework).
- [ ] No `print()` anywhere. No bare `logging.basicConfig()`. No `logger.error(str(exc))` without `exc_info=True`.
- [ ] `CancelledError` handled separately in any place an `except Exception` is used.
- [ ] If the route accepts secrets/PII, redaction processor covers the new field names.
- [ ] If the route streams, logs are emitted at stream end, not start.
- [ ] If the route calls a Ray deployment, `request_id` is forwarded in the payload.
- [ ] New domain exception classes have stable `code` strings — don't rename them later (dashboards depend on them).

## Anti-patterns (don't)

- ❌ `log.error(f"failed: {exc}")` — no `exc_info`, no traceback.
- ❌ `try: ...; except Exception as e: log.exception(...); raise` — fine, but only if you're at the boundary. Inside a helper, just `raise`.
- ❌ `try: ...; except Exception: pass` — silently swallowing. Always at least log + re-raise, or do nothing (let it propagate).
- ❌ `log.info(f"user {user.email} logged in")` — PII in unstructured message; not searchable.
- ❌ Logging the request body of every request "for debugging" — PII risk + log volume + cost.
- ❌ Sending stack traces to clients (`return {"error": str(traceback.format_exc())}`).
- ❌ Putting a `print(exc)` next to a real `log.exception` "to be safe" — print goes nowhere structured.
- ❌ Catching `BaseException` (catches `KeyboardInterrupt`, `SystemExit`, `CancelledError` together — pretty much always wrong).
- ❌ Logging at `error` what should be `warning` (rate-limited request, expected retry succeeded). Inflates error dashboards, drowns real signals.
- ❌ Distinct event names for the same thing (`user.login.failed` vs `auth.failed.login` vs `LOGIN_FAIL`). Pick one and stick with it.

## Reference skills / docs

- `docs/rules/api.md` — error contract (the JSON shape returned to clients).
- `docs/rules/streaming.md` — streaming-specific cancellation/error patterns.
- `docs/rules/security.md` — security-event logging.
- **security-review** skill — verifies log output doesn't leak secrets.