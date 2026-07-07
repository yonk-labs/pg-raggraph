FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[server,mcp]"

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# In-container 0.0.0.0 is correct (the container boundary is the network
# boundary); pgrg refuses this bind unless PGRG_SERVER_API_KEY is set —
# docker-compose.prod.yml supplies it (PR-217).
CMD ["pgrg", "serve", "--host", "0.0.0.0", "-p", "8080"]
