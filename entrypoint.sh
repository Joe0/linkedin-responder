#!/bin/sh
set -e

# Seed framework.md to persistent volume if not already there
if [ ! -f /app/instructions/framework.md ]; then
    echo "[entrypoint] Seeding framework.md to persistent volume..."
    mkdir -p /app/instructions
    cp /app/framework.md.seed /app/instructions/framework.md
fi

exec python main.py
