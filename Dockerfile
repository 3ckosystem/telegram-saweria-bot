# Image resmi Playwright + Python + semua deps browser ready
FROM mcr.microsoft.com/playwright/python:v1.46.0-noble

# Set workdir
WORKDIR /app

# Siapkan venv (opsional, base image sudah punya Python lengkap)
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy & install dependencies lebih dulu biar layer bisa cache
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source code
COPY . .

# Pastikan browser sudah terpasang (tanpa --with-deps)
RUN python -m playwright install chromium

# Railway akan set $PORT (auto)
CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
