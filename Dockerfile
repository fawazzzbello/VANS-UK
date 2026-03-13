FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Default: run the API server.
# Override CMD in Railway/docker-compose for workers:
#   violation-engine:      python -m src.processing.violation_engine
#   notification-service:  python -m src.alerting.notification_service
#   anpr-processor:        python -m src.ingestion.anpr_processor
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
