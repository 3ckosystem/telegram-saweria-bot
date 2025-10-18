FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN python -m playwright install chromium

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
