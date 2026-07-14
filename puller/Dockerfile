# Puller: blinkpy clip fetcher. Pure-Python, multi-arch (runs on the Pi's arm64).
FROM python:3.11.15-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY puller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip check

COPY common/ ./common/
COPY puller/ ./

USER 1000:1000
CMD ["python", "puller.py"]
