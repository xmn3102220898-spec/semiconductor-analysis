FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    PRODUCTION_DATA_FILE=/app/data/production_data.csv \
    PRODUCTION_DB_FILE=/app/storage/production.db \
    DIAGNOSIS_DB_FILE=/app/storage/diagnosis_history.db \
    OUTPUT_DIR=/app/output \
    HF_HOME=/app/model-cache

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY data ./data
COPY knowledge_base ./knowledge_base
COPY main_api.py .

RUN groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser \
    && mkdir -p /app/storage /app/output /app/model-cache \
    && chown -R appuser:appuser \
       /app/storage /app/output /app/model-cache

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["python", "-m", "uvicorn", "main_api:app", "--host", "0.0.0.0", "--port", "8000"]
