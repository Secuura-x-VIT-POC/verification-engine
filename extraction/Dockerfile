FROM python:3.11-slim-bookworm

# Install system dependencies for PP-ChatOCR image/PDF processing.
# Text and boxes come only from PP-ChatOCR; PyMuPDF is used only for PDF rasterization.
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/extraction

ENV PYTHONPATH=/app

# Default command to run the demo caching script
CMD ["python", "-m", "extraction.scripts.cache_demo"]
