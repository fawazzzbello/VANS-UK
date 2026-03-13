FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# API server
FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ANPR Processor worker
FROM base AS anpr-processor
CMD ["python", "-m", "src.ingestion.anpr_processor"]

# Violation Engine worker
FROM base AS violation-engine
CMD ["python", "-m", "src.processing.violation_engine"]

# Notification Service worker
FROM base AS notification-service
CMD ["python", "-m", "src.alerting.notification_service"]

# Ingestion workers
FROM base AS ingestion-highways
CMD ["python", "execution/ingest_highways.py"]

FROM base AS ingestion-tfl
CMD ["python", "execution/ingest_tfl.py"]
