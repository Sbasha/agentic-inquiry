FROM python:3.13-slim

WORKDIR /app

# Install system dependencies for tree-sitter
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY agentic_inquiry/ agentic_inquiry/
COPY config/ config/
COPY extensions/ extensions/
COPY scripts/entrypoint.py entrypoint.py

# Install dependencies
RUN uv sync --frozen --no-dev

# Pre-download the embedding model into the container image
# This avoids HuggingFace rate limits and slow cold starts
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Server port. Cloud Run requires a non-loopback listen address. The process
# serves nothing without both INQUIRY_SERVER_HOST and an API key.
ENV PORT=8080
ENV INQUIRY_SERVER_HOST=0.0.0.0
EXPOSE 8080

CMD ["uv", "run", "python", "entrypoint.py"]
