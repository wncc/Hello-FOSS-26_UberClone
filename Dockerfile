FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data /app/state

COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY requirements.txt /tmp/root-requirements.txt

RUN pip install --no-cache-dir \
    -r /tmp/backend-requirements.txt \
    -r /tmp/root-requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
