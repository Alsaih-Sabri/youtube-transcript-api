# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8010

COPY pyproject.toml README.md ./
COPY youtube_transcript_api ./youtube_transcript_api

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8010

ENTRYPOINT ["youtube_transcript_api"]