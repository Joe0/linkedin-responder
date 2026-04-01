FROM python:3.12-slim

# Install system deps + Node.js (for Claude Code CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code --unsafe-perm

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Seed file: framework.md baked into image, copied to PVC on first boot
RUN cp /app/instructions/framework.md /app/instructions/framework.md.seed

# Persistent dirs (mounted as PVCs in production)
VOLUME ["/app/data", "/app/uploads", "/app/instructions"]

ENV PORT=8000
EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
