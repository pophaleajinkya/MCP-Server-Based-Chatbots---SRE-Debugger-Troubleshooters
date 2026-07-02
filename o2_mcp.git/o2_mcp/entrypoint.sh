#!/bin/sh
set -e

cd /app
echo "Starting Uvicorn server on port 8010..."
export PYTHONPATH=/app:$PYTHONPATH
exec uvicorn app:app --host 0.0.0.0 --port 8010 --workers 2 --log-level info
