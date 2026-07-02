#!/bin/sh
set -e

echo "Starting Uvicorn server on port 8010..."
export PYTHONPATH=/app/src:$PYTHONPATH
# 1 worker: the agent is IO-bound (LLM + MCP calls) not CPU-bound.
# Multiple workers multiply Redis connections (4 workers × 20 pool = 80 connections)
# and cause MCP session affinity issues behind Istio load balancing.
# For horizontal scaling, run more pods/containers — not more workers per pod.
exec uvicorn main:app --app-dir /app/src --host 0.0.0.0 --port 8010 --workers 1 --log-level info
