#!/bin/sh
set -e

cd /app

# KITT deploy: Akeyless secret file (see kitt.yml secrets.files destination)
if [ -f /secrets/.env.valid8_mcp ]; then
  echo "Loading environment from /secrets/.env.valid8_mcp"
  set -a
  # shellcheck disable=SC1091
  . /secrets/.env.valid8_mcp
  set +a
fi

echo "Starting Valid8 MCP Server on port 8015..."
export PYTHONPATH=/app:$PYTHONPATH
exec uvicorn app:app --host 0.0.0.0 --port 8015 --workers 2 --log-level info
