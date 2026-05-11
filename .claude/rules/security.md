# Security rules

Hard rules. Apply by default. Only deviate with a comment + approval.

## 1. Secrets

- **No secret in source code, logs, comments, error messages, fixtures, frontend bundles, image layers, or LLM prompts.**
- All secrets via env, loaded into a `pydantic-settings` `Settings` class as `SecretStr`. Validate length/format at startup, fail fast if missing.
- `.env` is gitignored. `.env.example` is committed and lists every key with placeholder.
- Rotation: 90 days default, 30 days for high-value (root keys, prod DB, JWT signing keys).
- If a secret is committed: **rotate first**, then remove from history. Treat as compromised.

## 2. Authentication & authorization

- Every route is authenticated by default. Public routes have an explicit `Depends(allow_anonymous)` so audit is visible.
- Auth lives in middleware (`app/core/middleware.py`). Routes get the principal via `Depends(get_current_user)`.
- **Authorization is per-route and per-resource.** Authentication ≠ authorization. Every read/write of a user-owned resource checks that the principal owns it (or has admin role).
- Use **404 Not Found** instead of 403 when hiding existence is preferable. Pick one and document.
- Passwords: `argon2-cffi` (preferred) or `bcrypt` (cost ≥ 12). Never sha256/md5/pbkdf2-low.
- JWT: HS256 (≥ 256-bit secret) or RS256/EdDSA. Always verify `aud`, `iss`, `exp`. Reject `alg: none`.
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax` (or `Strict` for high-value).
- API keys: prefix-tagged (`sk_live_…`), stored hashed (like passwords), per-key rate limit, revocation endpoint.

## 3. Input validation

- Every route input is a pydantic model with `model_config = ConfigDict(extra="forbid")`.
- Bound every list (`max_length`) and string (`max_length`). No unbounded `list[Any]`.
- Validate at the schema (`@field_validator`), not in route bodies.
- File uploads: cap size, check magic bytes (not extension), strip EXIF for user images, store outside web root.
- Pydantic create/update schemas exclude server-controlled fields (`id`, `created_at`, `is_admin`, `tenant_id`).

## 4. Output safety

- Every route declares `response_model=...`. No undeclared fields leak.
- Don't return: hashed passwords, internal database IDs, full user objects when not needed, model API keys, system prompts.
- Add a **PII / secret scrubber** on LLM outputs (regex/Presidio) before returning to the user.
- HTML rendering of model output: escape (`autoescape=True` in Jinja2). Never `dangerouslySetInnerHTML` from model output without DOMPurify-grade sanitization.
- URLs in output: validate scheme allowlist (`https`, `mailto`); reject/rewrite others.

## 5. Encryption

- TLS everywhere. Reject HTTP at the LB. `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- At rest: managed encryption (AWS KMS, GCP CMEK) for DB, S3, snapshots. Don't roll your own.
- In motion between services: mTLS or signed tokens. Trust the network only inside a VPC with strict security groups.

## 6. Injection

- **SQL** via ORM with parameter binding. `text()` only with `bindparams`. **Never f-string into SQL.**
- **OS commands** via `subprocess.run([list], shell=False)`. No `shell=True` with interpolation.
- **Headers**: never set `Set-Cookie`, `Location`, or arbitrary headers from unvalidated user input (`\r\n` smuggling).
- **Templates**: Jinja2 with `autoescape=True`. Never `Template(user_input).render()`.

## 7. Deserialization

- **Never `pickle.loads(untrusted)`.** Same for `yaml.load` (use `yaml.safe_load`), `joblib.load(untrusted)`, `dill.loads`.
- `torch.load` always with `weights_only=True` (default in PyTorch 2.6+; explicit for older).
- Model weights: **safetensors** only. `.pt`/`.bin`/`.ckpt` from external sources need conversion in an isolated process.
- HuggingFace `trust_remote_code=True` only for pinned commit SHAs of vetted repos. Documented in `app/models/<x>.py`.

## 8. SSRF

- Routes that fetch URLs (RAG ingest, image-from-URL, tool calls):
  - Scheme allowlist: `https://` only.
  - Block private/link-local: 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16, IPv6 fc/7, ::1.
  - Block cloud metadata: `169.254.169.254`, `fd00:ec2::254`.
  - Resolve DNS once, dial that IP — defeat rebinding.
  - Timeouts: 5s connect, 30s read. Max body size. Max redirects 3.

## 9. Rate limiting & abuse

- Every state-changing endpoint: rate limit per principal (not per IP).
- Heavy endpoints (model inference): low limit (e.g. 60/min/user). Read endpoints: higher (600/min/user).
- Per-user **token budget** for LLM endpoints — hard cap output tokens × cost per day.
- Tool-call loops: max depth 10, error out beyond.
- Long-input attacks: cap context tokens at the API layer.

## 10. Logging & monitoring

- Every auth event logged with principal + IP + UA + request_id.
- **Never log**: secrets, full headers, auth route bodies, PII without explicit policy approval.
- Add a regex-based redaction filter at the logger handler (catches stray secrets in any log line).
- `request_id` propagates through every log line and is returned in `X-Request-Id` header.
- Metrics: 4xx rate by endpoint (probing), 401/403 spikes, sudden 200 drop.
- Alert on: > N 401s for one principal in a minute, new admin login, 5xx spike.

## 11. Misconfiguration

- `DEBUG=False` in prod. No stack traces to clients.
- CORS: explicit origin list, never `*`. Don't combine `*` with credentials.
- `TrustedHostMiddleware` set to your real hosts.
- `ProxyHeadersMiddleware` enabled when behind a proxy.
- Disable `/docs` and `/openapi.json` in prod (or auth-gate them) unless intentionally public.

## 12. Ray / cluster

- Ray dashboard (`:8265`) and Ray Serve API: **never** internet-exposed. Bind localhost or behind authenticated reverse proxy.
- Ray Client port (10001): unauthenticated; treat cluster network as trusted; firewall.
- Cluster nodes do not run untrusted code. Tool-call deployments that execute code (sandboxes) use hard isolation (gVisor/Firecracker/nsjail), not just Docker.

## 13. LLM-specific

- System prompts contain **no secrets** (extractable via prompt injection).
- Tool authorization is server-side. The model claiming an action does not authorize it; the API behind the tool does.
- Bind the principal at request entry; pass into every tool call. Never derive principal from model output.
- High-risk tools (write, send, transfer) require server-side scope check + idempotency key.
- Output moderation (classifier) for consumer-facing endpoints.
- Untrusted text in context (RAG docs, web fetches) marked clearly; high-risk operations gated behind two-call extract→act pattern.
- Image / audio / video uploads have their own rate limits and size caps separate from text.

## 14. Dependencies

- `uv.lock` is canonical. CI runs `uv sync --frozen`.
- Vulnerability scan on every PR: `pip-audit` + `osv-scanner`. Block on Critical.
- Security exception list at `.security/ignore.toml` — every entry has issue # and review date.
- New dep checklist before adding: maintainership, install footprint, source (PyPI only, no `git+https`), no typosquatting.

## 15. Webhooks & integrations

- Sign outgoing webhooks (HMAC over body + timestamp; receiver verifies and rejects if `|now − ts| > 5 min`).
- Verify incoming webhooks the same way.
- Don't trust integration responses without validation; treat as user input.

## 16. CI/CD

- Pin actions by SHA, not by tag. Tags are mutable.
- `GITHUB_TOKEN`: minimum scope per job (`permissions: contents: read` default).
- PR-from-fork workflows have no secrets. Never `pull_request_target` for untrusted code.
- Container base images pinned by digest, rebuilt monthly for CVE patches.
- Build provenance attestation (SLSA Level 2+) on shipped artifacts.

## 17. Incident response

- Suspected breach = rotate, isolate, log-mine in that order.
- Compromise of a long-lived secret = full rotation of any secret in the same blast radius.
- Post-mortem within 5 business days. Detection-gap fixes are part of the remediation, not a follow-up ticket.

## Anti-patterns (don't)

- ❌ "Just for now" hardcoded credentials.
- ❌ `try: ... except Exception: pass` — swallows security errors and `CancelledError`.
- ❌ Client-side validation only.
- ❌ "Security through obscurity" (hidden URLs, custom crypto).
- ❌ Disabling CSRF / CORS / TrustedHost to "make tests work".
- ❌ Logging the request body of an auth route to "help debugging".
- ❌ Putting secrets in URL query strings.
- ❌ Using `eval` / `exec` on any string derived from user input or LLM output.

## Reference skills

- **security-review** — apply during PR review.
- **llm-security** — apply for any LLM-facing change.
- **secrets-supply-chain** — apply when wiring auth, adding deps, building images.