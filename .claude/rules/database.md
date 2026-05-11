# Database rules

Hard rules + common pitfalls for any feature touching the database. Follow these by default; only deviate with a comment explaining why.

## Stack assumptions

- **SQLAlchemy 2.0** async ORM (`AsyncSession`, `select()` 2.0 style) on top of asyncpg/aiomysql/aiosqlite — pick one driver per service.
- **Alembic** for migrations.
- **pydantic** schemas at the API boundary; never pass ORM models out of the service layer.

If you must use a different stack (raw asyncpg, SQLModel, Tortoise), the rules below still apply — adapt the syntax.

## 1. Connection pool

- **Use a single pool per process**, owned by the FastAPI lifespan, stashed on `app.state.db`.
  ```python
  from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
  engine = create_async_engine(
      settings.db_url,
      pool_size=10,                # steady-state max connections
      max_overflow=10,             # burst headroom
      pool_pre_ping=True,          # detect dead conns from PgBouncer / restarts
      pool_recycle=1800,           # recycle conns every 30 min
  )
  SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
  ```
- **Never `create_engine()` per request** — that opens a brand-new pool every time.
- **Right-size**: `pool_size` ≤ DB's `max_connections` ÷ replicas. Behind PgBouncer transaction-pooling, `pool_size` can be small (5–10) per process.
- For Ray Serve replicas: each replica has its own pool — multiply by `num_replicas` when sizing the DB.

## 2. Sessions

- **One session per request** via FastAPI dependency:
  ```python
  async def get_db() -> AsyncIterator[AsyncSession]:
      async with SessionLocal() as session:
          yield session
  ```
- Session ends with the request — never store sessions on `app.state` or in a singleton.
- `expire_on_commit=False` — otherwise objects detach after commit and the next attribute access re-queries unexpectedly.
- **Don't share a session across `asyncio.gather`** — sessions are not concurrent-safe. Open one session per coroutine, or serialize the calls.

## 3. The N+1 problem

The single most common DB bug. Symptoms: 1 query becomes hundreds; latency scales linearly with result count.

**Bad:**
```python
users = (await db.execute(select(User))).scalars().all()
for u in users:
    print(u.posts)         # one SELECT per user — N+1
```

**Fix — eager load** (`selectinload` for collections, `joinedload` for one-to-one):
```python
users = (await db.execute(
    select(User).options(selectinload(User.posts))
)).scalars().all()
```

- Default to **`selectinload`** for `*-to-many` (one extra query, no row explosion).
- Use **`joinedload`** for `*-to-one` when you'll always need the related object (one query via JOIN).
- For nested: `selectinload(User.posts).selectinload(Post.comments)`.
- **In code review, scan every loop over query results** for attribute access on relationships — that's where N+1 hides.

To detect at runtime, log raw SQL in dev (`echo=True` on engine) and watch for the same `SELECT ... WHERE ... = $1` repeating with different params.

## 4. Transactions

- Use the explicit `async with session.begin()` block — it commits on success, rolls back on exception.
  ```python
  async with session.begin():
      session.add(user)
      await session.flush()
      session.add(profile_for(user))
      # commit on exit
  ```
- **One transaction per logical unit of work**. A request that does 3 unrelated writes can be 3 separate transactions if any can stand alone — keeps lock duration small.
- **Don't await network calls inside a transaction** (HTTP, S3, model inference). Long-held DB locks block other writers. Either:
  - Do the network call before the transaction and pass the result in, or
  - Use the outbox pattern (write a row, process async).
- **Idempotent operations**: prefer `INSERT ... ON CONFLICT DO NOTHING/UPDATE` over `SELECT then INSERT` (race-free).

## 5. Locking

- For "read, decide, write" sequences (counter increments, balance updates), use `SELECT ... FOR UPDATE`:
  ```python
  row = (await db.execute(select(Account).where(Account.id == aid).with_for_update())).scalar_one()
  row.balance -= amount
  ```
- Or, better, **let the database do the math atomically**:
  ```python
  await db.execute(update(Account).where(Account.id == aid).values(balance=Account.balance - amount))
  ```
- Detect deadlocks: PostgreSQL surfaces `40P01`. Wrap critical paths in a small retry-with-backoff loop (3 attempts, jitter) and log the pattern — repeated deadlocks signal lock-order issues.

## 6. Migrations (Alembic)

- One migration per logical schema change. Never edit a merged migration — write a new one.
- **Backwards-compatible deploys**: schema change first → app deploy → cleanup migration. Don't drop a column the previous version still reads.
- **Long-running migrations** (`ALTER TABLE` on big tables, adding NOT NULL with default): break into steps:
  1. Add column nullable.
  2. Backfill in batches (separate script/job).
  3. Add NOT NULL constraint.
- Avoid implicit table rewrites — `ALTER COLUMN ... TYPE` may rewrite the whole table. Check with `EXPLAIN`.
- Never auto-run migrations on app startup in prod. Run them as a separate step in the deploy pipeline so failures don't crash the API.

## 7. Indexes

- Add an index for **every column used in `WHERE`, `JOIN`, or `ORDER BY`** on a query that scans more than a few hundred rows.
- Composite indexes follow the leftmost-prefix rule: `(a, b, c)` accelerates `WHERE a=` and `WHERE a= AND b=`, not `WHERE b=`.
- Don't over-index — every index slows writes. Use `pg_stat_user_indexes` to find unused ones.
- For high-cardinality + range queries, consider partial indexes (`WHERE active = true`).
- Add migration + a `EXPLAIN ANALYZE` snippet in the PR description showing index usage.

## 8. Queries

- Use SQLAlchemy 2.0 style (`select()`, `update()`, `delete()`) — clearer, async-native. Avoid the legacy `Query` API.
- Project only columns you need: `select(User.id, User.email)` is cheaper than `select(User)`.
- For pagination: **keyset (cursor) pagination** beats `OFFSET` for tables > ~10k rows — `OFFSET 100000` scans 100k rows.
- Use `.scalar_one()` / `.scalar_one_or_none()` instead of `.first()` when you expect exactly one row — fails loudly on duplicates.

## 9. Connection budgets in async + Ray Serve world

- **Ray Serve replicas have their own pools**. Sizing: `replicas × pool_size + max_overflow ≤ DB max_connections − headroom`.
- **PgBouncer (transaction mode)** is strongly recommended in front of PostgreSQL — flatten thousands of app conns into ~50 actual DB conns. Disable SQLAlchemy `pool_use_lifo` features that rely on session state.
- **Read replicas**: route read-only traffic to a separate engine (and pool). Mark routes / functions as read-only and dispatch accordingly. Don't mix on the same session.

## 10. Observability

- Log query slow log (≥ 100 ms) with the SQL + params hash (never the full params if PII).
- Tag spans with `db.statement_kind` (select/update/insert/delete) and table.
- Track per-request DB time alongside total request time — DB shouldn't dominate p99.

## 11. Anti-patterns (don't)

- ❌ `db.commit()` inside a loop iterating over thousands of rows. Batch.
- ❌ `await session.refresh(obj)` after every write to "make sure" — it issues another query. Trust the ORM.
- ❌ Using ORM objects past the request lifecycle. Detach (or convert to pydantic) before stashing in cache / passing to background task.
- ❌ Catch + swallow `IntegrityError` to "handle duplicates" — use `ON CONFLICT` instead. Catching loses the constraint context.
- ❌ Storing JSON blobs to avoid schema work. Future-you will hate it. Use proper columns; reach for JSON only for genuinely schemaless data.
- ❌ `SELECT *` in raw SQL — fragile to schema changes.

## 12. Testing

- Use a real Postgres in tests (Docker), **not** SQLite — they have different SQL dialects, isolation behavior, and constraint enforcement.
- Wrap each test in a transaction that rolls back at teardown; each test sees a clean DB without truncates.
- Never share a session across tests; `pytest-asyncio` fixture-per-test is correct.
- Mock the DB only at the very top (route layer with `dependency_overrides`) — service-layer tests should hit a real DB.