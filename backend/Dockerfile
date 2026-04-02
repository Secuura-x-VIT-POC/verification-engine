FROM python:3.10-slim

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt

RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY extraction extraction

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
