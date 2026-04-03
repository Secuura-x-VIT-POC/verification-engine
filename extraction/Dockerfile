FROM python:3.11-slim-bookworm

# Install system dependencies and local Tesseract for OCR fallback
# We use 'libgl1' instead of 'libgl1-mesa-glx' for modern Debian compatibility
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/extraction

ENV PYTHONPATH=/app

# Default command to run the extraction API service
CMD ["uvicorn", "extraction.main:app", "--host", "0.0.0.0", "--port", "8000"]
