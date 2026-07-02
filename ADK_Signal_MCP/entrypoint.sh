#!/bin/sh
set -e

cd /app

# KITT deploy: Akeyless secret file (see kitt.yml secrets.files destination)
if [ -f /secrets/.env.signal_mcp ]; then
  echo "Loading environment from /secrets/.env.signal_mcp"
  set -a
  # shellcheck disable=SC1091
  . /secrets/.env.signal_mcp
  set +a
fi

echo "Starting Signal MCP Server on port 8020..."
export PYTHONPATH=/app:$PYTHONPATH
exec uvicorn app:app --host 0.0.0.0 --port 8020 --workers 2 --log-level info
