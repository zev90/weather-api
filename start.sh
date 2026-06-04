#!/bin/bash
# China Weather API 启动脚本
# 使用: bash start.sh

echo "=========================================="
echo "  China Weather API for AI Agents"
echo "=========================================="

cd "$(dirname "$0")"

# 安装依赖
pip install flask requests -q 2>/dev/null

echo ""
echo "启动服务..."
echo "API 地址: http://127.0.0.1:8080"
echo "示例请求: http://127.0.0.1:8080/v1/weather?city=张家界&days=5"
echo ""

python app.py
