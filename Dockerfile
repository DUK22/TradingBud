# ----------------------------------------------------------------------------
# Stage 1: build do CSS (Tailwind) — gera app/static/app.css com Node.
# ----------------------------------------------------------------------------
FROM node:22-alpine AS css
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tailwind.config.js ./
COPY app/static/src ./app/static/src
COPY app/templates ./app/templates
RUN npm run build:css

# ----------------------------------------------------------------------------
# Stage 2: runtime Python (gunicorn). Não depende de Node.
# ----------------------------------------------------------------------------
FROM python:3.11-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    SKIP_SCHEMA_INIT=1
WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .
# CSS fresco do stage anterior (sobrescreve o versionado).
COPY --from=css /build/app/static/app.css ./app/static/app.css

RUN chmod +x docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "3", "wsgi:app"]
