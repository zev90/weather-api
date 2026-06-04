#!/bin/bash
# China Weather API - Railway 启动脚本
set -e

echo "Starting China Weather API x402..."
echo "Port: ${PORT:-8080}"

# 用gunicorn生产服务器(多worker)
exec gunicorn app:app \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 2 \
    --timeout 30 \
    --access-logfile - \
    --error-logfile -
