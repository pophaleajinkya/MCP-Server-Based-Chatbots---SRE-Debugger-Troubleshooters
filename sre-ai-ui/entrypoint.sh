#!/bin/sh
set -e

echo "Starting sre-ai-ui on port ${PORT:-3000}..."
exec npm run start
