FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Railway uses PORT env variable
ENV PORT=8000

# Run with PORT from environment
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
