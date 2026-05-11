# API rules

Hard rules for any HTTP endpoint. These supplement the **conventions.md** style guide with behavior rules — what the API must do, not how to format the code.

## 1. Versioning

- All public routes live under `/v1/...`. Internal routes use `/internal/...` and are not part of the contract.
- **Never break a v1 contract**. Removing/renaming a field, narrowing types, changing required fields → ship under `/v2/...` instead. Old version stays until clients migrate.
- New optional fields (request or response) are not breaking. Adding optional fields with safe defaults is allowed in-place.
- Deprecation: respond with `Deprecation` and `Sunset` headers (RFC 8594). Log usage so you know who's still calling.

## 2. Idempotency

- All `POST` that creates resources, sends notifications, charges money, or invokes external side-effects must accept an `Idempotency-Key` header.
- Server stores `(idempotency_key → response)` for ≥ 24h. Repeats return the original response, not a fresh execution.
- `PUT` and `DELETE` are idempotent by definition — make them so. Hitting `DELETE /x/123` twice should not 404 the second time; return 204 both times.
- For background work triggered by a request, dedupe on the idempotency key inside the worker.

> For exception **logging** (what to log when an exception is caught, where to put exception handlers, redaction), see `docs/rules/logging.md`. This section covers the JSON shape returned to the client.

## 3. Error contract

- Always return a structured error body, not a bare string:
  ```json
  {
    "error": {
      "code": "model_unavailable",
      "message": "The model is currently warming up.",
      "details": {"retry_after_ms": 5000},
      "request_id": "abc-123"
    }
  }
  ```
- `code` is a stable machine-readable enum. Clients branch on `code`, never on `message` (which can be localized / changed).
- HTTP status mapping:
  - **400** — client sent invalid input (validation, malformed JSON).
  - **401** — missing/invalid auth.
  - **403** — authenticated but not allowed.
  - **404** — resource doesn't exist (or you don't want to confirm it does).
  - **409** — state conflict (idempotency key reused with different body, optimistic lock failed).
  - **422** — semantically invalid (FastAPI default for pydantic errors).
  - **429** — rate limited; include `Retry-After` header.
  - **500** — your bug. Never expose stack trace to clients.
  - **502/503/504** — upstream failure (model deployment down, DB timeout). Include `Retry-After` if transient.
- **Never** return 200 with `{"success": false}`. Use the right status code.
- Log every 5xx with `request_id`, full stack, and the request payload (sanitized).

## 4. Request validation

- Always declare a pydantic request model. Never `dict` parameters in route signatures.
- `model_config = ConfigDict(extra="forbid")` — reject unknown fields. Clients sending typo'd field names should get an error, not silent drop.
- Bound every list (`max_length=...`) and string (`max_length=...`). Otherwise a malicious client can OOM you.
- Validate at the schema, not in the route body. Custom rules → `@field_validator` / `@model_validator`.

## 5. Response shape

- Always declare `response_model=...`. No undeclared fields leak out.
- Pagination envelope (consistent across endpoints):
  ```json
  {
    "data": [...],
    "next_cursor": "opaque-string-or-null",
    "has_more": true
  }
  ```
  Use **cursor pagination**, not `?page=N&size=M` — page numbers break under writes (rows shift).
- Lists: declare a maximum page size (e.g. 100). Default to 20.
- For single-resource GETs, return the resource at the top level — no envelope.
- ISO-8601 strings for datetimes (`...Z`, UTC). Never epoch ints (ambiguous units, no timezone).
- Use enums (string-valued) for fixed sets, not free-text strings.

## 6. Auth

- Auth lives in middleware (`app/core/middleware.py`), not per-route.
- Use `Depends(get_current_user)` to inject the authenticated principal into routes that need it. Never read headers directly.
- Service-to-service auth: short-lived JWT with audience + issuer claims. Never share long-lived API keys between services.
- All endpoints are authenticated by default. Mark public ones with an explicit `dependencies=[Depends(allow_anonymous)]` so the audit is visible.

## 7. Rate limiting

- Apply at the API gateway when possible. If self-hosted, use a sliding-window limiter (Redis-backed).
- Limit per-principal (user/api-key), not per-IP — IP is shared/spoofable.
- Different limits per endpoint class:
  - Heavy (model inference): low (e.g. 60/min/user).
  - Read (list, get): higher (e.g. 600/min/user).
- Return `429` + `Retry-After` + `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers.

## 8. Timeouts and cancellation

- Every external call (DB, model handle, HTTP) needs a timeout. Default `httpx` timeout is `5s` — explicitly set per call.
- FastAPI middleware should enforce a request-level deadline (e.g. 30s) and cancel work via `asyncio.wait_for`.
- When a client disconnects, FastAPI raises `asyncio.CancelledError` in the handler. Propagate cancellation to downstream (DeploymentHandle has cancellation support) — don't keep computing for a gone client.

## 9. Concurrency safety

- Don't mutate shared state in handlers. `app.state.<x>` is read-only after lifespan setup.
- Don't cache per-request data on module-level globals. It will leak across requests.
- For per-user / per-tenant counters, use the DB (atomic update) or Redis (atomic ops). Never an in-memory dict.

## 10. Observability

- Every request gets a `request_id` (middleware generates if absent). Echo it in response header `X-Request-Id` and in every log line.
- Log: method, path, status, latency, principal, request_id. **Don't** log request bodies of authenticated routes by default (PII risk); allow at debug level only.
- Emit metrics: requests/sec, error rate, p50/p95/p99 latency, per-route. Prometheus.
- Trace: each request opens a span; downstream calls (DB, model, HTTP) are child spans. OpenTelemetry.

> Full logging + exception-logging rules (the seven required fields, log levels, FastAPI exception handlers, `CancelledError`, streaming, Ray correlation, redaction, sampling) live in `docs/rules/logging.md`.

## 11. Schema evolution checklist

Before merging any change to a request/response schema:

- [ ] Is this a new optional field with a default? **Safe.**
- [ ] Is this a new required field? **Breaking** — needs `/v2/` or default value.
- [ ] Renaming a field? **Breaking** — keep both for one release with deprecation.
- [ ] Tightening a type (e.g. `string` → `enum`)? **Breaking** — keep accepting old values for one release.
- [ ] Loosening a type (e.g. `enum` → `string`)? Safe for input, **breaking** for output (clients may pattern-match).
- [ ] Removing a field? **Breaking** — drop only after deprecation period.

## 12. OpenAPI

- Every route has `summary`, `description`, `tags`. The auto-generated `/docs` is the API contract; treat it as a deliverable.
- Provide `examples=[...]` on schema fields and `responses={...}` for each non-default status.
- Keep one `tags=` per router; tags become navigation in the docs UI.

## 13. File uploads

- Use `UploadFile` (streaming) — never `bytes` (loads entire file into memory).
- Cap size in middleware (e.g. 10 MB JSON, 100 MB upload). Reject early with 413.
- Validate content-type and magic bytes; don't trust the filename extension.
- For very large uploads, use pre-signed S3/GCS URLs and have the client upload directly — don't proxy GBs through the API.

## 14. Anti-patterns (don't)

- ❌ `?id=1,2,3` comma-separated in URLs. Use `POST /batch` with a JSON list when count > a few.
- ❌ Returning DB / ORM objects directly. Convert to pydantic.
- ❌ Catching all exceptions in a route. Let exception handlers do their job.
- ❌ Putting business logic in middleware. Middleware is for cross-cutting concerns (auth, logging, CORS).
- ❌ Verb-y URLs (`/createUser`, `/getOrders`). Use REST nouns + HTTP verbs.
- ❌ Mixing v1 + v2 in one router file. One file per version per resource.