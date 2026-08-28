FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face / faster-whisper model cache
ENV HF_HOME=/models
ENV TRANSFORMERS_CACHE=/models
ENV FASTER_WHISPER_MODEL=large-v3
ENV FASTER_WHISPER_DEVICE=cpu
ENV FASTER_WHISPER_COMPUTE_TYPE=int8

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
