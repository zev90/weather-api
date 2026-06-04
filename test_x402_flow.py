#!/usr/bin/env python3
"""
x402 支付流程端到端测试
模拟 AI Agent 发现 API → 收到 402 → 付款获取 token → 重试获取数据
"""

import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8080"

def step(title, emoji="▶"):
    print(f"\n{'='*60}")
    print(f" {emoji}  {title}")
    print(f"{'='*60}")

def test_flow():
    # ===== Step 1: Agent 发现 API (读取首页) =====
    step("Step 1: Agent 发现 API", "🔍")
    r = requests.get(f"{BASE_URL}/v1/info")
    info = r.json()
    print(f"服务: {info['service']}")
    print(f"描述: {info['description']}")
    print(f"定价: {json.dumps(info['pricing'], indent=2)}")

    # ===== Step 2: Agent 直接请求天气 (无支付) =====
    step("Step 2: 无支付直接请求 → 应收 HTTP 402", "💳")
    r = requests.get(f"{BASE_URL}/v1/weather?city=张家界&days=3")
    print(f"HTTP Status: {r.status_code}")
    body = r.json()
    print(f"响应类型: {body.get('type')}")
    print(f"标题: {body.get('title')}")
    print(f"金额: ${body['payment']['amount']} {body['payment']['currency']}")
    print(f"收款地址: {body['payment']['recipient'][:20]}...")

    if r.status_code != 402:
        print("❌ 预期 402 但得到其他状态码!")
        return False
    print("✅ HTTP 402 返回正确!")

    # ===== Step 3: Agent 发起支付 (模拟) =====
    step("Step 3: Agent 模拟支付获 Token", "💰")
    r = requests.post(f"{BASE_URL}/v1/pay", json={
        "amount": 0.01,
        "request_id": "agent-trip-张家界-20260604"
    })
    pay_result = r.json()
    print(f"支付状态: {pay_result['success']}")
    token = pay_result['payment_token']
    print(f"Token (前30字符): {token[:30]}...")
    print(f"金额: ${pay_result['amount']}")

    # ===== Step 4: Agent 带 Token 重试 =====
    step("Step 4: 带 Payment Token 请求天气 → 应收 200", "📊")
    headers = {"X-402-Payment-Token": token}
    r = requests.get(f"{BASE_URL}/v1/weather?city=张家界&days=3", headers=headers)
    print(f"HTTP Status: {r.status_code}")

    if r.status_code != 200:
        print(f"❌ 预期 200 但得到 {r.status_code}")
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:500])
        return False
    print("✅ 支付验证通过!")

    data = r.json()
    print(f"城市: {data['city']}")
    print(f"预报天数: {len(data['forecast'])}")
    for f in data['forecast']:
        adv = f.get('travel_advice', [])
        print(f"  {f['date']}: {f['weather']} | {f['temp_low']}~{f['temp_high']}°C")
        if adv:
            print(f"    建议: {adv[0]}")

    # ===== Step 5: 验证 Token 过期拒绝 =====
    step("Step 5: 无效 Token → 应收拒绝", "🚫")
    headers = {"X-402-Payment-Token": "invalid-token-fake"}
    r = requests.get(f"{BASE_URL}/v1/weather?city=北京&days=1", headers=headers)
    print(f"HTTP Status: {r.status_code}")
    if r.status_code == 402:
        print("✅ 无效 Token 正确拒绝!")
        print(f"错误: {r.json().get('error')}")
    else:
        print(f"⚠️ 预期 402 但得到 {r.status_code}")

    # ===== Step 6: 验证免费端点仍可用 =====
    step("Step 6: 验证无需付费的端点", "✅")
    r = requests.get(f"{BASE_URL}/health")
    print(f"Health: {r.status_code} - {r.json()['status']}")

    r = requests.get(f"{BASE_URL}/v1/cities")
    print(f"Cities API: {r.status_code} - 支持 {r.json()['total']} 个城市")

    print(f"\n{'='*60}")
    print(" 🎉 全部流程走通!")
    print(f"{'='*60}")
    return True


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════╗
    ║   China Weather API - x402 支付流程测试      ║
    ║   模拟 AI Agent 完整的发现→付费→消费流程     ║
    ╚══════════════════════════════════════════════╝
    """)

    success = test_flow()
    sys.exit(0 if success else 1)
