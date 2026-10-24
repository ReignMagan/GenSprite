FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir . \
    && mkdir /data \
    && chown 10001:10001 /data
USER 10001:10001
ENTRYPOINT ["gensprite-mcp", "--output-dir", "/data"]
