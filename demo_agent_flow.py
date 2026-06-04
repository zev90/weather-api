#!/usr/bin/env python3
"""
x402 支付流程 - Agent视角演示
模拟一个旅游规划AI Agent 发现 API → 付款 → 获取天气数据 的完整交互
"""
import requests
import json
import time

BASE = "http://127.0.0.1:8080"

def run():
    print("=" * 55)
    print("   🤖 旅游规划 Agent 调用中国天气 API演示")
    print("   x402 支付流程 (Agent消费视角)")
    print("=" * 55)

    # Step 1: Agent 查看 API 首页
    print("\n[Agent] 我在规划张家界行程，先看天气API首页...")
    r = requests.get(f"{BASE}/v1/info")
    info = r.json()
    print(f"[API]  {info['service']}")
    print(f"[API]  {info['description']}")
    for k,v in info['pricing'].items():
        print(f"[API]  定价 {k}: {v}")

    # Step 2: 无支付请求 → 402
    print(f"\n[Agent] GET /v1/weather?city=张家界&days=5")
    r = requests.get(f"{BASE}/v1/weather?city=张家界&days=5")
    print(f"[API]  HTTP {r.status_code} Payment Required")
    body = r.json()
    print(f"[API]  请支付: ${body['payment']['amount']} {body['payment']['currency']}")
    print(f"[API]  链: {body['payment']['chain']}  收款: {body['payment']['recipient'][:12]}...")

    # Step 3: Agent 付款获 token
    print(f"\n[Agent] 好的，支付 ${body['payment']['amount']} ...")
    print(f"[Agent] POST /v1/pay (模拟支付)")
    r = requests.post(f"{BASE}/v1/pay", json={
        "amount": float(body['payment']['amount']),
        "request_id": f"trip-张家界-{int(time.time())}"
    })
    pay = r.json()
    print(f"[API]  支付成功! Token: {pay['payment_token'][:30]}...")

    # Step 4: 带token重试
    print(f"\n[Agent] 带Token重试天气查询...")
    headers = {"X-402-Payment-Token": pay['payment_token']}
    r = requests.get(f"{BASE}/v1/weather?city=张家界&days=5", headers=headers)
    data = r.json()
    print(f"[API]  HTTP {r.status_code} ✅")
    print(f"[API]  {data['city']} 未来{len(data['forecast'])}天预报:")
    for f in data['forecast']:
        adv = f.get('travel_advice', [])
        print(f"  {f['date']}: {f['weather']}  {f['temp_low']}~{f['temp_high']}°C")
        if adv: print(f"    💡 {adv[0]}")
    print(f"\n[Agent] 已拿到天气数据，继续规划行程...")

    # Step 5: 批量多城市
    print(f"\n[Agent] 批量查询: 桂林+西安+杭州 (需要multi_batch定价)")
    r = requests.get(f"{BASE}/v1/weather?city=桂林&days=3", headers=headers)
    r2 = requests.get(f"{BASE}/v1/weather?city=西安&days=3", headers=headers)
    r3 = requests.get(f"{BASE}/v1/weather?city=杭州&days=3", headers=headers)
    print(f"[API]  桂林: {r.json()['forecast'][0]['weather']}")
    print(f"[API]  西安: {r2.json()['forecast'][0]['weather']}")
    print(f"[API]  杭州: {r3.json()['forecast'][0]['weather']}")

    print(f"\n{'='*55}")
    print("   ✅ 完整 x402 消费流程演示完毕")
    print(f"{'='*55}")

if __name__ == "__main__":
    run()
