FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api
COPY mcp_server.py .
COPY config/default_medication_map.json ./config/default_medication_map.json

ENV MEDS_DATABASE_PATH=/data/medications.db
ENV MEDS_STORAGE_DIR=/data/storage
ENV MEDS_DEFAULT_MAPPING_PATH=/app/config/default_medication_map.json

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
