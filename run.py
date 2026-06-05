"""Ponto de entrada da aplicação.

Uso:
    python run.py
ou:
    flask --app run run

Variáveis de ambiente:
    FLASK_DEBUG=1   liga o debugger (NUNCA em produção — expõe console RCE).
    PORT=5000       porta do servidor.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, host="127.0.0.1", port=port)
