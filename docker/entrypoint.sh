#!/bin/sh
set -e

python - <<'PY'
import os
import time

import psycopg

database_url = os.environ.get("DATABASE_URL")
if database_url:
    for attempt in range(60):
        try:
            with psycopg.connect(database_url, connect_timeout=3):
                break
        except psycopg.OperationalError:
            if attempt == 59:
                raise
            time.sleep(2)
PY

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-false}" = "true" ]; then
    python manage.py collectstatic --clear --noinput
fi

exec "$@"
