FROM python:3.11-slim

WORKDIR /app

# Install dependencies (sqlite3 is built-in to Python)
RUN pip install --no-cache-dir pandas

# Copy CSV and build script
COPY Medications-2026-03-26-2026-04-26.csv .
COPY build_medications_db.py .

# Create volume mount point for database
VOLUME ["/data"]

# Build database on startup
CMD ["python", "build_medications_db.py"]
