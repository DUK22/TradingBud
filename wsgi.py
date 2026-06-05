"""Entrypoint WSGI para servidores de produção.

    # Linux / Docker:
    gunicorn -b 0.0.0.0:8000 wsgi:app
    # Windows:
    waitress-serve --listen=0.0.0.0:8000 wsgi:app

Em produção, aplique as migrações antes (flask db upgrade) e defina
SKIP_SCHEMA_INIT=1 para o auto-upgrade não correr entre workers.
"""
from app import create_app

app = create_app()
