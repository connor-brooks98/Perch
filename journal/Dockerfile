FROM python:3.11.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY journal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY common/ ./common/
COPY journal/ ./journal/
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "30", "journal.app:create_app()"]
