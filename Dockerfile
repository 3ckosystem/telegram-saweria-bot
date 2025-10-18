# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# PENTING: pakai shell agar ${PORT} diexpand
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
