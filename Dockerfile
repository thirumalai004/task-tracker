# ---- base: dependencies and application code ----
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py integration_test.py ./
COPY static ./static

# ---- test: unit tests run during the build; a failing test stops the build ----
FROM base AS test
COPY test_app.py ./
RUN python -m unittest -v test_app

# ---- final: the image that gets deployed ----
FROM base AS final
# Defaults only. DB_PASSWORD has no default on purpose: the app refuses to start without it.
ENV APP_PORT=5000 \
    APP_ENV=dev \
    DB_HOST=db \
    DB_PORT=5432 \
    DB_NAME=tasks \
    DB_USER=postgres
RUN useradd --create-home appuser
USER appuser
EXPOSE 5000
# Docker runs this every few seconds; deploy.sh and `docker ps` use the result.
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('APP_PORT','5000'), timeout=2)" || exit 1
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${APP_PORT} --workers 1 --threads 32 'app:create_app()'"]
