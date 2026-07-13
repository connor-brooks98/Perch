# Classifier: ffmpeg frame extraction + local TFLite inference.
FROM python:3.11.15-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY classifier/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip check

COPY common/ ./common/
COPY classifier/ ./

USER 1000:1000
CMD ["python", "watcher.py"]
