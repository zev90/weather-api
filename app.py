"""
China Weather API for AI Agents
为境外旅游规划Agent提供中国城市天气预报 + 旅游建议
Powered by wttr.in (free) / QWeather (optional)
With x402 Payment Middleware (Coinbase HTTP 402 Standard)
"""

import requests
import json
import hmac
import hashlib
import base64
import time
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, make_response, render_template

app = Flask(__name__)

# ============================================================
# 来访记录 (Agent调用监控)
# ============================================================
from collections import deque
import threading

visit_log = deque(maxlen=100)  # 最近100条来访记录
visit_lock = threading.Lock()
start_time = time.time()

@app.before_request
def log_visit():
    """记录每次API请求"""
    if request.path.startswith("/v1/"):
        paid = "X-402-Payment-Token" in request.headers
        entry = {
            "time": datetime.now().strftime("%m-%d %H:%M:%S"),
            "ip": request.remote_addr,
            "endpoint": request.path,
            "method": request.method,
            "paid": paid,
            "city": request.args.get("city", ""),
            "user_agent": (request.headers.get("User-Agent", "") or "")[:80],
        }
        with visit_lock:
            visit_log.appendleft(entry)

@app.route("/v1/stats")
def stats():
    """来访记录面板 (手机可看)"""
    with visit_lock:
        recent = list(visit_log)[:50]
    total = len(recent)
    paid_count = sum(1 for v in recent if v["paid"])
    cities = list(set(v["city"] for v in recent if v["city"]))
    uptime = int(time.time() - start_time)
    h, m = uptime // 3600, (uptime % 3600) // 60
    return jsonify({
        "uptime": f"{h}h {m}m",
        "total_requests": total,
        "paid_requests": paid_count,
        "unpaid_402": total - paid_count,
        "cities_queried": cities,
        "recent": recent,
        "tip": "打开 /dashboard 看可视化面板"
    })

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", base_url=request.host_url.rstrip("/"))

# ============================================================
# x402 支付中间件 (HTTP 402 Payment Required)
# ============================================================

# --- 计费配置 ---
X402_ENABLED = True              # 是否启用付费
X402_MODE = "dev"                # "dev" 模拟支付 | "live" Coinbase真实支付
X402_SECRET = os.environ.get("X402_SECRET", "dev-secret-change-in-production")
X402_TOKEN_TTL = 300             # 支付token有效期(秒), 5分钟

# 定价表 (USD)
PRICING = {
    "single_7d":  0.01,    # 单城市7天预报
    "single_14d": 0.02,    # 单城市14天预报
    "multi_batch": 0.05,   # 批量多城市
}

# Coinbase x402 facilitator (生产模式使用)
COINBASE_FACILITATOR = "https://x402.org/facilitator"
RECIPIENT_ADDRESS = os.environ.get("RECIPIENT_ADDRESS", "0x0000000000000000000000000000000000000000")


def generate_payment_token(amount, request_id):
    """生成支付token (HMAC-SHA256签名)"""
    payload = f"{amount}|{request_id}|{int(time.time())}"
    sig = hmac.new(X402_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = base64.b64encode(f"{payload}|{sig}".encode()).decode()
    return token


def verify_payment_token(token):
    """验证支付token"""
    try:
        decoded = base64.b64decode(token).decode()
        parts = decoded.split("|")
        if len(parts) != 4:
            return False, "invalid token format"
        amount, request_id, ts_str, sig = parts
        # 检查过期
        if int(time.time()) - int(ts_str) > X402_TOKEN_TTL:
            return False, "token expired"
        # 验证签名
        payload = f"{amount}|{request_id}|{ts_str}"
        expected = hmac.new(X402_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return False, "invalid signature"
        return True, {"amount": amount, "request_id": request_id}
    except Exception:
        return False, "token decode failed"


def build_402_response(amount, currency="USDC", chain="base"):
    """构建 HTTP 402 响应 (x402标准格式)"""
    body = {
        "type": "x402",
        "title": "Payment Required",
        "description": f"This API costs ${amount} USD per request. Pay in {currency} on {chain}.",
        "payment": {
            "amount": str(amount),
            "currency": currency,
            "chain": chain,
            "network": "base" if chain == "base" else chain,
            "recipient": RECIPIENT_ADDRESS,
            "facilitator": COINBASE_FACILITATOR,
        },
        "_dev_note": "Dev mode: use /v1/pay to get a payment token for testing" if X402_MODE == "dev" else None,
    }
    resp = make_response(jsonify(body), 402)
    resp.headers["Content-Type"] = "application/json"
    resp.headers["X-402-Payment"] = f"amount={amount},currency={currency},chain={chain}"
    return resp


def require_payment(price_key="single_7d"):
    """x402 付费装饰器: 拦截未付费请求"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not X402_ENABLED:
                return f(*args, **kwargs)

            amount = PRICING.get(price_key, 0.01)
            token = request.headers.get("X-402-Payment-Token", "")

            if not token:
                return build_402_response(amount)

            valid, info = verify_payment_token(token)
            if not valid:
                return jsonify({"error": f"Payment verification failed: {info}", "code": "INVALID_TOKEN"}), 402

            # 验证通过，注入支付信息到请求上下文
            request.x402_payment = info
            return f(*args, **kwargs)
        return wrapper
    return decorator


# --- 开发模式: 模拟支付端点 (Agent可用此端点获取token) ---
@app.route("/v1/pay", methods=["POST"])
def mock_payment():
    """开发模式: 模拟支付获token。生产环境下此端点不存在。"""
    if X402_MODE != "dev":
        return jsonify({"error": "Not available in live mode"}), 404

    body = request.get_json(silent=True) or {}
    amount = str(body.get("amount", 0.01))
    request_id = body.get("request_id", "demo-" + str(int(time.time())))
    token = generate_payment_token(amount, request_id)
    return jsonify({
        "success": True,
        "payment_token": token,
        "amount": amount,
        "request_id": request_id,
        "usage": f"Add header: X-402-Payment-Token: {token}",
        "curl_example": f'curl -H "X-402-Payment-Token: {token}" "http://localhost:8080/v1/weather?city=张家界&days=7"',
    })

# 天气数据源: "wttr" (免费, 无需Key) 或 "qweather" (需Key)
DATA_SOURCE = "wttr"

# 和风天气 Key (仅当 DATA_SOURCE="qweather" 时使用)
QWEATHER_KEY = ""

# 中国城市名 -> wttr.in 查询名映射
CITY_MAP = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "西安": "Xian",
    "南京": "Nanjing",
    "武汉": "Wuhan",
    "苏州": "Suzhou",
    "长沙": "Changsha",
    "厦门": "Xiamen",
    "昆明": "Kunming",
    "桂林": "Guilin",
    # 山岳
    "黄山": "Huangshan",
    "华山": "Huayin",
    "泰山": "Taian",
    "峨眉山": "Emeishan",
    "庐山": "Lushan",
    "长白山": "Changbaishan",
    "玉龙雪山": "Lijiang",
    # 喀斯特
    "张家界": "Zhangjiajie",
    "阳朔": "Yangshuo",
    # 水乡/湖泊
    "西湖": "Hangzhou",
    "千岛湖": "Qiandaohu",
    "洱海": "Dali",
    "泸沽湖": "Luguhu",
    # 古城/历史
    "故宫": "Beijing",
    "长城": "Beijing",
    "兵马俑": "Xian",
    "莫高窟": "Dunhuang",
    "丽江古城": "Lijiang",
    "平遥古城": "Pingyao",
    # 高原
    "九寨沟": "Jiuzhaigou",
    "布达拉宫": "Lhasa",
    "稻城亚丁": "Daocheng",
    "香格里拉": "Shangri-La",
    "色达": "Seda",
    # 海滨
    "三亚": "Sanya",
    "鼓浪屿": "Xiamen",
    "青岛": "Qingdao",
    "大连": "Dalian",
    # 冰雪
    "哈尔滨": "Harbin",
    "雪乡": "Harbin",
    "漠河": "Mohe",
    # 城市休闲
    "大理": "Dali",
    "丽江": "Lijiang",
    "敦煌": "Dunhuang",
    "拉萨": "Lhasa",
    "乌鲁木齐": "Urumqi",
    "天津": "Tianjin",
    "郑州": "Zhengzhou",
    "济南": "Jinan",
    "合肥": "Hefei",
    "福州": "Fuzhou",
    "南昌": "Nanchang",
    "南宁": "Nanning",
    "贵阳": "Guiyang",
    "太原": "Taiyuan",
    "沈阳": "Shenyang",
    "长春": "Changchun",
    "呼和浩特": "Hohhot",
    "银川": "Yinchuan",
    "西宁": "Xining",
    "兰州": "Lanzhou",
    "海口": "Haikou",
    "珠海": "Zhuhai",
    "佛山": "Foshan",
    "东莞": "Dongguan",
    "温州": "Wenzhou",
    "绍兴": "Shaoxing",
    "洛阳": "Luoyang",
    "凤凰": "Fenghuang",
    "稻城": "Daocheng",
    "延吉": "Yanji",
}


# ============================================================
# 旅游建议引擎 (你的知识壁垒)
# ============================================================

SCENIC_ADVICE = {
    # ===== 山岳类 =====
    "黄山": {
        "rain_ok": "小雨+云雾=云海最佳观赏时机，反而不建议晴天去",
        "rain_bad": "暴雨请勿上山，索道可能停运，改去宏村/屯溪老街",
        "hot": "山顶比山下低约10°C，仍建议带薄外套",
        "cold": "冬季有雾凇奇观，需冰爪+登山杖",
    },
    "华山": {
        "rain_ok": "小雨路面湿滑，长空栈道/鹞子翻身可能关闭",
        "rain_bad": "暴雨严禁登山，花岗岩路面极滑，索道停运风险高",
        "hot": "暴晒严重，无遮蔽路段占70%，务必4L水/人",
        "cold": "冬季积雪封山风险高，出发前确认是否开放",
    },
    "泰山": {
        "rain_ok": "雨中登泰山别有气势，但十八盘台阶滑",
        "rain_bad": "暴雨不建议，雷击风险（泰山是雷暴高发区）",
        "hot": "全程台阶为主，暴晒段多，夜爬可避开高温",
        "cold": "山顶风极大，体感比山下低15°C，需羽绒服",
    },
    "峨眉山": {
        "rain_ok": "常年多雨是常态，金顶可能被云雾遮蔽",
        "rain_bad": "暴雨导致山路泥泞，猴群更活跃（抢食风险增加）",
        "hot": "海拔3000m山顶凉爽，但山脚湿热",
        "cold": "冬季金顶-10°C常见，路面结冰需冰爪",
    },
    "庐山": {
        "rain_ok": "庐山烟雨是经典意境，含鄱口云雾壮观",
        "rain_bad": "暴雨引发山洪风险，三叠泉可能关闭",
        "hot": "夏季避暑胜地，山顶比九江低10°C",
        "cold": "冬季有雨凇雾凇，但山路结冰危险",
    },
    "长白山": {
        "rain_ok": "小雨不影响游览，天池可能被云雾遮挡",
        "rain_bad": "暴雨天池关闭，山路有滑坡风险",
        "hot": "夏季山顶仅10°C左右，必须带厚外套",
        "cold": "-30°C常见，暴露皮肤10分钟冻伤，防风面罩必备",
    },
    "玉龙雪山": {
        "rain_ok": "小雨索道正常，但能见度差看不到主峰",
        "rain_bad": "暴雨索道必停，山下蓝月谷仍可游览",
        "hot": "夏季也要穿羽绒服上山，山下丽江30°C山上0°C",
        "cold": "大风天气索道停运几率高，出发前确认",
    },

    # ===== 喀斯特/溶洞类 =====
    "张家界": {
        "rain_ok": "小雨不影响游览，天子山云雾缭绕别有风味",
        "rain_bad": "大雨导致能见度极低，玻璃栈道关闭风险，建议延期",
        "hot": "森林公园树荫充足，做好防晒即可",
        "cold": "景区照常开放，注意台阶结冰",
    },
    "桂林": {
        "rain_ok": "烟雨漓江是经典画面，小雨不影响游船",
        "rain_bad": "暴雨后漓江变浑，游船可能停航",
        "hot": "溶洞内常年20°C，可作避暑选择",
        "cold": "冬季偏湿冷，但游客少体验好",
    },
    "阳朔": {
        "rain_ok": "小雨骑行十里画廊别有风味，遇龙河竹筏正常",
        "rain_bad": "暴雨遇龙河竹筏停运，改室内攀岩馆或西街",
        "hot": "骑行务必早出发（6:00-10:00），中午暴晒",
        "cold": "冬季湿冷，民宿暖气不一定充足，确认后再订",
    },

    # ===== 水乡/湖泊类 =====
    "西湖": {
        "rain_ok": "雨西湖十景之一，雨中漫步别有韵味",
        "rain_bad": "雷雨天勿在湖边逗留，可改室内茶楼",
        "hot": "环湖绿荫充足，骑行注意防暑",
        "cold": "断桥残雪是经典冬景",
    },
    "千岛湖": {
        "rain_ok": "游船正常，岛屿之间有遮蔽",
        "rain_bad": "暴雨游船停航，改湖边度假酒店",
        "hot": "水上项目为主，做好防晒，水温舒适",
        "cold": "冬季游船减少班次，部分岛屿关闭",
    },
    "洱海": {
        "rain_ok": "环海骑行略滑但可行，雨后彩虹高概率",
        "rain_bad": "暴雨不建议骑行，改古城咖啡馆/扎染体验",
        "hot": "紫外线极强（海拔2000m），30分钟可晒伤",
        "cold": "风大（下关风），骑行防风外套必备",
    },
    "泸沽湖": {
        "rain_ok": "雨中湖景别有韵味，猪槽船正常",
        "rain_bad": "暴雨山路有落石风险，丽江到泸沽湖公路危险",
        "hot": "海拔2700m，夏季白天25°C夜间10°C，带厚外套",
        "cold": "冬季可能下雪封路，出发前确认路况",
    },

    # ===== 古城/历史类 =====
    "故宫": {
        "rain_ok": "室内展览丰富，不受天气影响",
        "rain_bad": "中轴线露天段积水，但东西六宫可逛",
        "hot": "广场无遮阳，务必带伞+水",
        "cold": "室内有暖气，但户外排队注意保暖",
    },
    "长城": {
        "rain_ok": "小雨可爬，石板路略滑注意安全",
        "rain_bad": "暴雨不建议，石阶极滑且无遮蔽",
        "hot": "带足水，无遮挡路段暴晒严重",
        "cold": "北风极大，比市区体感低10°C",
    },
    "兵马俑": {
        "rain_ok": "室内展厅为主，不受天气影响",
        "rain_bad": "从停车场到入口有一段露天步行，需雨具",
        "hot": "展厅内人流量大时闷热，随身小风扇实用",
        "cold": "室内外温差不大，正常冬季穿搭即可",
    },
    "莫高窟": {
        "rain_ok": "完全室内参观，不受影响",
        "rain_bad": "敦煌极少暴雨，罕见情况不影响",
        "hot": "夏季极端干燥炎热（40°C+），避开12:00-16:00",
        "cold": "冬季正常开放，游客极少，体验最佳但冷",
    },
    "丽江古城": {
        "rain_ok": "石板路遇水反光很美，但注意防滑",
        "rain_bad": "暴雨古城排水良好不影响，但束河可能积水",
        "hot": "紫外线强+干燥，补水+防晒双管齐下",
        "cold": "昼夜温差大，夜间10°C以下需薄羽绒服",
    },
    "平遥古城": {
        "rain_ok": "城内商铺密集，雨天可沿廊檐走",
        "rain_bad": "城门附近低洼处可能积水",
        "hot": "黄土高原夏季干热，中午避开城墙（无遮蔽）",
        "cold": "冬季烧煤取暖，空气质量可能较差",
    },

    # ===== 高原/藏区类 =====
    "九寨沟": {
        "rain_ok": "小雨无碍，但需穿防水鞋",
        "rain_bad": "暴雨有山洪风险，景区可能临时关闭",
        "hot": "海拔2000+米，夏季也只有22°C左右，很舒适",
        "cold": "冬季部分栈道关闭，但冰瀑景观绝美",
    },
    "布达拉宫": {
        "rain_ok": "室内参观为主，雨天不影响",
        "rain_bad": "暴雨罕见，拉萨全年少雨",
        "hot": "海拔3650m，紫外线极强，晒伤比中暑更危险",
        "cold": "冬季白天10°C夜间-10°C，宫殿内无暖气，穿足",
    },
    "稻城亚丁": {
        "rain_ok": "小雨正常，牛奶海五色海路泥泞",
        "rain_bad": "暴雨取消长线徒步，短线冲古寺仍可走",
        "hot": "海拔4000m+夏季也需冲锋衣，气温10-20°C",
        "cold": "10月后可能大雪封山，需确认开放状态",
    },
    "香格里拉": {
        "rain_ok": "小雨普达措正常游，松赞林寺室内为主",
        "rain_bad": "暴雨虎跳峡徒步危险，改松赞林寺+古城",
        "hot": "夏季20°C左右，但紫外线极强",
        "cold": "冬季-10°C以下常见，部分客栈歇业",
    },
    "色达": {
        "rain_ok": "小雨正常，红房子在雨中色彩更浓",
        "rain_bad": "暴雨山路危险，壤塘到色达段注意落石",
        "hot": "海拔4000m夏季最高25°C，但高反是更大问题",
        "cold": "-20°C常见，五明佛学院部分区域冬季关闭",
    },

    # ===== 海滨/海岛类 =====
    "三亚": {
        "rain_ok": "热带阵雨来得快去得也快，不影响下水",
        "rain_bad": "台风天严禁海滩活动，酒店泳池也关闭",
        "hot": "全年高温，12:00-15:00避开户外",
        "cold": "冬季25°C+，反而是最佳旅游季节",
    },
    "鼓浪屿": {
        "rain_ok": "雨中老建筑更有味道，钢琴博物馆室内",
        "rain_bad": "暴雨轮渡可能停航，上岛前确认航班状态",
        "hot": "夏季湿热，岛上步行为主，避开正午",
        "cold": "冬季风大，轮渡颠簸，备晕船药",
    },
    "青岛": {
        "rain_ok": "雨中八大关别有风情，啤酒博物馆室内",
        "rain_bad": "暴雨海边风浪大，禁止下海",
        "hot": "8月最热但比内陆低5°C，海水浴场正当时",
        "cold": "冬季海风刺骨，体感比气温低10°C",
    },
    "大连": {
        "rain_ok": "小雨海洋馆/发现王国室内正常",
        "rain_bad": "暴雨滨海路有滑坡风险，改星海广场室内",
        "hot": "夏季凉爽，是东北避暑首选",
        "cold": "冬季-10°C常见，海风极大，防风外套必备",
    },

    # ===== 冰雪/冬季专属 =====
    "哈尔滨": {
        "rain_ok": "市区室内景点丰富（中央大街商场/极地馆）",
        "rain_bad": "冰雪大世界下雨会融化冰雕，确认开放",
        "hot": "夏季35°C，但啤酒节/太阳岛正当时",
        "cold": "-30°C常态，冰雪大世界内-40°C，暖宝宝全身贴",
    },
    "雪乡": {
        "rain_ok": "下雨会破坏雪景，不建议",
        "rain_bad": "下雨一定不要去，雪化了就是普通农村",
        "hot": "夏季无雪，不是雪乡的正确打开方式",
        "cold": "-30°C以下，相机电池续航减半，备3块以上",
    },
    "漠河": {
        "rain_ok": "北极村雨中仍可游览，但极光看不到",
        "rain_bad": "暴雨罕见，不影响",
        "hot": "夏季20°C清爽宜人，极昼现象是卖点",
        "cold": "-40°C极寒，手机10分钟关机，泼水成冰经典打卡",
    },

    # ===== 城市休闲类 =====
    "成都": {
        "rain_ok": "茶馆/火锅/博物馆室内为主，雨天不影响",
        "rain_bad": "熊猫基地熊猫可能回室内，但仍可见",
        "hot": "火锅照吃不误，但户外景点（宽窄巷子）早晚去",
        "cold": "湿冷刺骨（魔法攻击），比北方-5°C更难熬",
    },
    "重庆": {
        "rain_ok": "雨天雾都更有味道，洪崖洞夜景更梦幻",
        "rain_bad": "暴雨导致部分步道湿滑，但轻轨/室内景点正常",
        "hot": "火炉之首，40°C常见，避开12:00-17:00户外",
        "cold": "冬季阴冷潮湿，火锅是最佳暖身方案",
    },
    "苏州": {
        "rain_ok": "雨中园林别有韵味，听雨轩就是为雨天设计的",
        "rain_bad": "暴雨不影响，园林/博物馆室内为主",
        "hot": "园林绿荫多但仍闷热，平江路建议傍晚去",
        "cold": "湿冷，园林内无暖气，穿足衣物",
    },
    "西安": {
        "rain_ok": "兵马俑/陕博室内为主，下雨不影响",
        "rain_bad": "城墙骑行会关闭，但城墙步行仍可",
        "hot": "干热（40°C+），兵马俑展厅人流量大时闷热",
        "cold": "干冷，城墙风大，体感比市区低5°C",
    },
}


def get_travel_advice(scenic, weather_code, temp_high, temp_low, wind_speed):
    """根据天气生成旅游建议"""
    advice = SCENIC_ADVICE.get(scenic, {})

    # 雨天判断
    is_rain = any(w in str(weather_code).lower() for w in ["rain", "drizzle", "shower", "雨", "阵雨", "暴雨"])
    is_heavy_rain = any(w in str(weather_code).lower() for w in ["heavy", "torrential", "暴雨", "大暴雨"])

    # 温度判断
    is_hot = temp_high >= 35
    is_cold = temp_low <= 0

    # 大风判断
    is_windy = wind_speed >= 20

    tips = []

    if is_heavy_rain:
        tips.append(advice.get("rain_bad", "暴雨天气，建议改室内景点"))
    elif is_rain:
        tips.append(advice.get("rain_ok", "小雨天气，仍可出行但需带雨具"))

    if is_hot:
        tips.append(advice.get("hot", "高温天气，注意防暑补水"))
    if is_cold:
        tips.append(advice.get("cold", "低温天气，注意保暖防滑"))

    if is_windy:
        tips.append("风力较大，索道/游船有停运风险")

    return tips if tips else ["天气状况良好，适宜出行"]


def generate_clothing_advice(temp_high, temp_low, weather_code):
    """根据天气生成穿衣建议"""
    is_rain = any(w in str(weather_code).lower() for w in ["rain", "drizzle", "shower", "雨"])

    advice = []
    if temp_low >= 25:
        advice = ["短袖短裤", "防晒衣/帽", "墨镜"]
    elif temp_low >= 18:
        advice = ["短袖+薄长裤", "薄外套（早晚用）"]
    elif temp_low >= 10:
        advice = ["长袖+薄外套", "长裤", "早晚可能需要卫衣"]
    elif temp_low >= 0:
        advice = ["毛衣/卫衣", "厚外套", "围巾可选"]
    else:
        advice = ["羽绒服", "保暖内衣", "手套围巾帽子"]

    if is_rain:
        advice.append("雨伞/雨衣")
    if temp_high - temp_low >= 12:
        advice.append("注意：昼夜温差大，建议洋葱式穿搭")

    return advice


# ============================================================
# 数据获取层
# ============================================================

def fetch_wttr(city_en, days=7, city_display=""):
    """从 wttr.in 获取天气 (免费, 无需Key)"""
    url = f"https://wttr.in/{city_en}?format=j1"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return parse_wttr(data, days, city_input=city_display)
    except Exception as e:
        return {"error": f"wttr.in 查询失败: {str(e)}"}


def parse_wttr(data, days, city_input=""):
    """解析 wttr.in JSON 为标准格式"""
    result = {
        "city": city_input or data.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", "Unknown"),
        "country": "China",
        "timezone": "Asia/Shanghai",
        "forecast": []
    }

    weather_entries = data.get("weather", [])
    count = 0
    for day_data in weather_entries:
        if count >= days:
            break
        date_str = day_data.get("date", "")
        for hourly in day_data.get("hourly", []):
            # 取每天中午的数据作为代表
            if "1200" in hourly.get("time", ""):
                temp_high = int(day_data.get("maxtempC", 0))
                temp_low = int(day_data.get("mintempC", 0))
                weather_desc = hourly.get("weatherDesc", [{}])[0].get("value", "")
                humidity = int(hourly.get("humidity", 0))
                wind_speed = int(hourly.get("windspeedKmph", 0))
                uv_index = int(hourly.get("uvIndex", 0))
                visibility = int(hourly.get("visibility", 10))

                result["forecast"].append({
                    "date": date_str,
                    "weather": weather_desc,
                    "temp_high": temp_high,
                    "temp_low": temp_low,
                    "humidity": humidity,
                    "wind_speed_kmh": wind_speed,
                    "uv_index": uv_index,
                    "visibility_km": visibility,
                })
                count += 1
                break

    return result


def fetch_qweather(city, days=7):
    """从和风天气获取 (需要Key, 数据更精准)"""
    if not QWEATHER_KEY:
        return {"error": "和风天气Key未配置"}

    # Step 1: 城市搜索
    geo_url = f"https://geoapi.qweather.com/v2/city/lookup?location={city}&key={QWEATHER_KEY}"
    try:
        geo_resp = requests.get(geo_url, timeout=10).json()
        if geo_resp.get("code") != "200":
            return {"error": f"城市搜索失败: {geo_resp}"}
        city_id = geo_resp["location"][0]["id"]
        city_name = geo_resp["location"][0]["name"]
    except Exception as e:
        return {"error": f"城市搜索异常: {str(e)}"}

    # Step 2: 获取天气预报
    weather_url = f"https://devapi.qweather.com/v7/weather/{days}d?location={city_id}&key={QWEATHER_KEY}"
    try:
        weather_resp = requests.get(weather_url, timeout=10).json()
        if weather_resp.get("code") != "200":
            return {"error": f"天气获取失败: {weather_resp}"}
    except Exception as e:
        return {"error": f"天气获取异常: {str(e)}"}

    forecast = []
    for day in weather_resp.get("daily", [])[:days]:
        forecast.append({
            "date": day.get("fxDate"),
            "weather": day.get("textDay"),
            "temp_high": int(day.get("tempMax", 0)),
            "temp_low": int(day.get("tempMin", 0)),
            "humidity": int(day.get("humidity", 0)),
            "wind_speed_kmh": int(day.get("windSpeedDay", 0)),
            "uv_index": int(day.get("uvIndex", 0)),
            "visibility_km": int(day.get("vis", 10)),
        })

    return {
        "city": city_name,
        "country": "China",
        "timezone": "Asia/Shanghai",
        "forecast": forecast
    }


# ============================================================
# API 路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html", base_url=request.host_url.rstrip("/"))

@app.route("/deploy")
def deploy_guide():
    return render_template("deploy.html")

@app.route("/v1/info")
def api_info():
    return jsonify({
        "service": "China Weather API v1.0",
        "description": "中国城市天气预报 + 旅游建议，专为AI旅游规划Agent设计",
        "usage": {
            "endpoint": "/v1/weather",
            "method": "GET",
            "params": {
                "city": "城市名称 (中文/pinyin/English, 必填)",
                "days": "预报天数 1-14, 默认7 (选填)",
                "travel": "是否附带旅游建议 true/false, 默认true (选填)",
                "format": "输出格式 json/html, 默认json (选填)"
            },
            "example": "/v1/weather?city=张家界&days=5&travel=true"
        },
        "pricing": {
            "single_city_7d": "$0.01 USD",
            "single_city_14d": "$0.02 USD",
            "multi_city_batch": "$0.05 USD per trip"
        }
    })


@app.route("/v1/weather", methods=["GET"])
@require_payment("single_7d")
def weather():
    city = request.args.get("city", "").strip()
    days = min(int(request.args.get("days", 7)), 14)
    travel = request.args.get("travel", "true").lower() != "false"
    output_format = request.args.get("format", "json").lower()

    if not city:
        return jsonify({"error": "city 参数必填"}), 400

    # 城市名解析
    city_query = CITY_MAP.get(city, city)

    # 获取天气数据
    if DATA_SOURCE == "qweather":
        data = fetch_qweather(city_query, days)
    else:
        data = fetch_wttr(city_query, days, city_display=city)

    if "error" in data:
        return jsonify(data), 500

    # 附加旅游建议
    if travel:
        for f in data["forecast"]:
            f["travel_advice"] = get_travel_advice(
                city, f["weather"], f["temp_high"], f["temp_low"], f["wind_speed_kmh"]
            )
            f["clothing"] = generate_clothing_advice(
                f["temp_high"], f["temp_low"], f["weather"]
            )

    if output_format == "html":
        return render_html(data)
    return jsonify(data)


def render_html(data):
    """生成移动端友好的HTML输出"""
    rows = ""
    for f in data["forecast"]:
        advice = "<br>".join(f.get("travel_advice", []))
        clothing = ", ".join(f.get("clothing", []))
        rows += f"""
        <div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:8px 0;background:#fff;">
            <div style="font-size:16px;font-weight:bold;color:#333;">{f['date']}</div>
            <div style="font-size:24px;margin:8px 0;color:#e65100;">{f['weather']} | {f['temp_low']}°C ~ {f['temp_high']}°C</div>
            <div style="font-size:13px;color:#666;">湿度 {f['humidity']}% | 风速 {f['wind_speed_kmh']}km/h | 紫外线 {f['uv_index']}</div>
            <div style="margin-top:8px;font-size:13px;color:#2e7d32;">旅游建议: {advice}</div>
            <div style="font-size:13px;color:#1565c0;">穿衣: {clothing}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{data['city']} 天气预报</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f5;padding:16px;margin:0;}}
h2{{color:#333;margin:8px 0;}}
</style>
</head>
<body>
<h2>{data['city']} 未来{len(data['forecast'])}天天气预报</h2>
{rows}
<p style="color:#999;font-size:12px;text-align:center;margin-top:16px;">China Weather API for AI Agents | wttr.in</p>
</body>
</html>"""


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/v1/cities")
def list_cities():
    """返回支持的城市列表 (Agent 可读取)"""
    return jsonify({
        "total": len(CITY_MAP),
        "cities": list(CITY_MAP.keys())
    })


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("=" * 60)
    print("  China Weather API for AI Agents")
    print(f"  http://0.0.0.0:{port}")
    print("  数据源:", DATA_SOURCE)
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
