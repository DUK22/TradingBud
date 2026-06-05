#!/bin/sh
set -e

# Aplica as migrações UMA vez (fora dos workers do gunicorn). Em produção o
# auto-upgrade no startup fica desligado via SKIP_SCHEMA_INIT=1 (ver Dockerfile).
echo "Aplicando migrações (flask db upgrade)..."
flask --app wsgi db upgrade

# Sobe o servidor (CMD do Dockerfile).
exec "$@"
