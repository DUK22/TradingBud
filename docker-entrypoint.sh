#!/bin/sh
set -e

# Aplica as migrações UMA vez (fora dos workers do gunicorn). Em produção o
# auto-upgrade no startup fica desligado via SKIP_SCHEMA_INIT=1 (ver Dockerfile).
echo "Aplicando migrações (flask db upgrade)..."
flask --app wsgi db upgrade

# Sobe o gunicorn na porta fornecida pelo provedor (Render define $PORT).
exec gunicorn -b "0.0.0.0:${PORT:-8000}" -w "${WEB_CONCURRENCY:-3}" wsgi:app
