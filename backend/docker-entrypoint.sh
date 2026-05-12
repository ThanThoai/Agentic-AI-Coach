#!/bin/sh
set -e

echo "[entrypoint] Applying database migrations..."
uv run alembic upgrade head
echo "[entrypoint] Migrations done. Running: $*"

exec "$@"
