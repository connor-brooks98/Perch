# Puller: blinkpy clip fetcher. Pure-Python, multi-arch (runs on the Pi's arm64).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY puller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY puller/ ./

CMD ["python", "puller.py"]
