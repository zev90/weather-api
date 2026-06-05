"""
MCP Server for China Weather API
让 Claude Desktop / Cursor 等 MCP 客户端直接调用天气查询

运行方式:
  python mcp_server.py           # stdio 模式 (Claude Desktop)
  python mcp_server.py --sse     # SSE 模式 (远程)
"""

import json
import os
import sys
from typing import Any

import requests

API_BASE = os.environ.get("WEATHER_API_BASE", "http://127.0.0.1:8080")
MCP_MODE = os.environ.get("MCP_MODE", "stdio")


# ============================================================
# MCP 协议工具实现 (通过 REST API 代理)
# ============================================================

def call_api(endpoint: str, params: dict | None = None) -> dict:
    """调用后端 REST API (自动处理 x402 支付流程)"""
    url = f"{API_BASE}{endpoint}"
    resp = requests.get(url, params=params, timeout=15)

    if resp.status_code == 402:
        # 收到 402 → 自动支付 (仅 dev 模式)
        payment = resp.json()
        amount = payment.get("accepts", [{}])[0].get("extra", {}).get("priceDisplay", "$0.01")
        amount_val = float(amount.replace("$", "").split()[0])

        pay_resp = requests.post(
            f"{API_BASE}/v1/pay",
            json={"amount": amount_val, "request_id": f"mcp-{os.urandom(4).hex()}"},
            timeout=10,
        )
        if pay_resp.status_code != 200:
            return {"error": f"Payment failed: {pay_resp.text}"}

        token = pay_resp.json()["payment_token"]
        resp = requests.get(
            url, params=params,
            headers={"X-402-Payment-Token": token},
            timeout=15,
        )

    if resp.status_code != 200:
        return {"error": f"API error {resp.status_code}: {resp.text[:200]}"}
    return resp.json()


def handle_get_weather(args: dict) -> dict:
    """获取中国城市天气预报 + 旅游建议"""
    city = args.get("city", "")
    if not city:
        return {"error": "city 参数必填"}
    days = args.get("days", 7)
    travel = args.get("travel", True)
    data = call_api("/v1/weather", {"city": city, "days": days, "travel": str(travel).lower()})
    return data


def handle_list_cities(args: dict) -> dict:
    """列出所有支持的城市"""
    data = call_api("/v1/cities")
    return data


def handle_get_info(args: dict) -> dict:
    """获取 API 信息和定价"""
    data = call_api("/v1/info")
    return data


TOOL_HANDLERS = {
    "get_weather": {
        "handler": handle_get_weather,
        "description": "获取中国城市天气预报，含温度、湿度、风速、紫外线等详细数据，以及旅游建议和穿衣建议",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，支持中文（如：张家界、北京、上海、桂林）",
                },
                "days": {
                    "type": "integer",
                    "description": "预报天数，1-14，默认7",
                    "default": 7,
                },
                "travel": {
                    "type": "boolean",
                    "description": "是否附带旅游建议，默认true",
                    "default": True,
                },
            },
            "required": ["city"],
        },
    },
    "list_cities": {
        "handler": handle_list_cities,
        "description": "列出所有支持查询天气的中国城市/景点",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "get_api_info": {
        "handler": handle_get_info,
        "description": "获取天气API的服务信息和使用说明",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
}


# ============================================================
# MCP stdio 协议实现 (简易版)
# ============================================================

def send_mcp(msg: dict):
    """向 stdout 发送 MCP 消息 (按协议要求)"""
    line = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def handle_mcp_request(msg: dict):
    """处理 MCP JSON-RPC 请求"""
    msg_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "initialize":
        send_mcp({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "serverInfo": {
                    "name": "china-weather-mcp",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "tools": {},
                },
            },
        })

    elif method == "tools/list":
        tools = []
        for name, info in TOOL_HANDLERS.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["input_schema"],
            })
        send_mcp({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": tools},
        })

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler_info = TOOL_HANDLERS.get(tool_name)

        if not handler_info:
            send_mcp({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            })
            return

        try:
            result = handler_info["handler"](tool_args)
            send_mcp({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
            })
        except Exception as e:
            send_mcp({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)},
            })

    else:
        send_mcp({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": None,
        })


def run_stdio():
    """stdio 模式: 逐行读取 stdin 并回复 stdout"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_mcp_request(msg)
        except json.JSONDecodeError:
            continue
        except SystemExit:
            raise
        except Exception:
            continue


def run_sse():
    """SSE 模式 (占位)"""
    print("SSE mode not yet implemented for standalone MCP server")
    print("Run without --sse for stdio mode (Claude Desktop compatible)")
    sys.exit(1)


if __name__ == "__main__":
    if "--sse" in sys.argv:
        run_sse()
    else:
        run_stdio()
