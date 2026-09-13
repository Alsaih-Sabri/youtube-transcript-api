# --------------------------------------------------
# Stage 1: Build & dependency compilation with uv
# --------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Cache mounts speed up rebuilds significantly
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    uv pip install --system --target=/deps -r requirements.txt

# --------------------------------------------------
# Stage 2: Minimal hardened runtime
# --------------------------------------------------
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Copy only installed libraries from builder stage
COPY --from=builder /deps /usr/local/lib/python3.12/site-packages
COPY main.py .

# Run as unprivileged standard non-root user (nobody)
USER 65534:65534

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]