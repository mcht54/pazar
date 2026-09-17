FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages ./packages
COPY services ./services
COPY alembic.ini .

ENV PYTHONPATH=/app

CMD ["celery", "-A", "services.worker.celery_app", "worker", "--loglevel=info"]
