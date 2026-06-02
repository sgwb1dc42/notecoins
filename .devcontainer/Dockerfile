# .devcontainer/Dockerfile
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Paquetes base + Node.js (tooling JS/CSS/HTML)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /workspaces/app

# Cache eficiente de dependencias Python
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install -U pip \
  && pip install -r /tmp/requirements.txt \
  && rm -f /tmp/requirements.txt
