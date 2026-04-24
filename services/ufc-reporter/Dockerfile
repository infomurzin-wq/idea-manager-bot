FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV UFC_REPORTER_RUNTIME_ROOT=/data/ufc-reporter

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY scripts /app/scripts
COPY templates /app/templates

CMD ["python", "-m", "ufc_reporter.cli", "railway-cron"]
