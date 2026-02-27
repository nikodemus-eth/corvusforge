# Corvusforge v0.4.0 — Multi-stage, minimal, SAOE-ready
# Build: docker build -t corvusforge:0.4.0 .
# Run:   docker run -p 8501:8501 corvusforge:0.4.0

FROM python:3.12-slim AS builder
WORKDIR /app

# Install build dependencies
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir hatch && hatch build

# Install the wheel
COPY . .
RUN pip install --no-cache-dir dist/corvusforge-0.4.0-py3-none-any.whl

# --- Production stage ---
FROM python:3.12-slim
WORKDIR /app

# Copy installed packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/corvusforge /usr/local/bin/corvusforge
COPY --from=builder /app/corvusforge /app/corvusforge

# Create data directories
RUN mkdir -p /app/.corvusforge/artifacts /app/.openclaw-data

# Environment defaults
ENV CORVUSFORGE_ENVIRONMENT=production
ENV CORVUSFORGE_DOCKER_MODE=true
ENV CORVUSFORGE_LEDGER_PATH=/app/.corvusforge/ledger.db
ENV CORVUSFORGE_THINGSTEAD_DATA=/app/.openclaw-data

EXPOSE 8501

# Default: launch Streamlit dashboard
CMD ["corvusforge", "ui"]
