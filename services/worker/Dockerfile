FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY packages ./packages
COPY services ./services
COPY alembic.ini .

ENV PYTHONPATH=/app

CMD ["celery", "-A", "services.worker.celery_app", "worker", "--loglevel=info"]
