#!/bin/bash
# China Weather API - Railway 启动脚本
set -e
cd "$(dirname "$0")"
echo "Starting China Weather API x402 on port ${PORT:-8080}"
exec python app.py
