FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BOT_DATA_DIR=/app/data \
    WORKSPACE_ROOT=/app/workspace

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY scripts /app/scripts
COPY docs /app/docs
COPY services/ufc-reporter /app/services/ufc-reporter

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data /app/workspace

CMD ["idea-manager-bot"]
