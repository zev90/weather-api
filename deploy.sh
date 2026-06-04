#!/bin/bash
# ====================================================
#  China Weather API x402 - 一键部署脚本
#  支持: Railway / Render / 任意VPS
#  用法: bash deploy.sh
# ====================================================
set -e

echo "========================================"
echo "  China Weather API x402 部署工具"
echo "========================================"

# 检查Python
python3 --version || { echo "需要Python3.8+"; exit 1; }

# 安装依赖
echo "[1/3] 安装依赖..."
pip install -r requirements.txt -q

# 生成生产密钥
echo "[2/3] 配置安全密钥..."
if [ ! -f .env ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env <<EOF
X402_MODE=dev
X402_SECRET=${SECRET}
RECIPIENT_ADDRESS=0x0000000000000000000000000000000000000000
PORT=8080
EOF
    echo "  已生成 .env 文件 (密钥: ${SECRET:0:16}...)"
fi

# 启动服务
echo "[3/3] 启动服务..."
PORT=${PORT:-8080}
echo "  监听端口: $PORT"
echo "  访问地址: http://0.0.0.0:$PORT"
echo "========================================"
echo "  公网地址 (部署平台会自动分配):"
echo "  Railway:  https://xxx.railway.app"
echo "  Render:   https://xxx.onrender.com"
echo "  VPS:      http://你的服务器IP:$PORT"
echo "========================================"

python app.py
