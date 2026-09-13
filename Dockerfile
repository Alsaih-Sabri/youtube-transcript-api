# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8010 \
    NO_BROWSER=true

COPY pyproject.toml README.md ./
COPY youtube_transcript_api ./youtube_transcript_api
COPY templates ./templates
COPY app.py ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir fastapi uvicorn pydantic requests defusedxml && \
    pip install --no-cache-dir --no-deps .

EXPOSE 8010

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8010", "--no-browser"]