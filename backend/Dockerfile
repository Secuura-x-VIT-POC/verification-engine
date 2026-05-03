FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PADDLEOCR_ENABLED=1 \
    TESSERACT_ENABLED=0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY extraction/requirements.txt /tmp/extraction-requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir \
        -r /tmp/backend-requirements.txt \
        -r /tmp/extraction-requirements.txt \
        numpy \
        paddlepaddle \
        paddleocr

COPY backend /app/backend
COPY extraction /app/extraction

RUN mkdir -p /app/uploads /app/tmp

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
