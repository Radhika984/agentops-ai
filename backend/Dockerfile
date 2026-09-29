FROM python:3.12-slim

WORKDIR /app

# uv is used for dependency management (matches backend/uv.lock).
RUN pip install --no-cache-dir uv

# Install dependencies first (separate layer from app code) so code
# changes don't invalidate the dependency-install cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Required so CI/orchestrators can tell "container running" apart from
# "container actually serving traffic" (see Phase 0 Common Mistakes).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
