FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data \
    TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata \
    HF_HOME=/home/app/.cache/huggingface

# French OCR model used by PyMuPDF's embedded Tesseract engine
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/backend.txt requirements/backend.txt
# CPU-only PyTorch keeps the image small (no CUDA libraries)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements/backend.txt

COPY backend backend
COPY scripts scripts
COPY sample_data sample_data

RUN useradd --create-home app && mkdir -p /app/data "$HF_HOME" && chown -R app:app /app /home/app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
