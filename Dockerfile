FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml requirements.lock ./
COPY gateway ./gateway
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --constraint requirements.lock --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir --constraint requirements.lock .

FROM python:3.12-slim AS runtime
RUN groupadd --gid 10001 gateway && useradd --uid 10001 --gid gateway --no-create-home gateway \
    && mkdir -p /app/data && chown gateway:gateway /app/data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY config ./config
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"
CMD ["llm-gateway", "serve", "--host", "0.0.0.0"]
