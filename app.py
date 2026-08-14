#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 v4 - 纯 API 模式
参考: weikkadd/zampto (pure API approach)

策略:
  1. 用 ZAMTO_COOKIE（cf_clearance + zampto_session + zampto_csrf）注入 requests.Session
  2. 通过 API 直接调用 /api/server/renew 续期
  3. 完全绕过浏览器，避免 Cloudflare Turnstile

环境变量:
  ZAMTO_COOKIE    必填  Cookie 字符串 "k1=v1; k2=v2"
  SERVER_ID       可选  服务器 ID（默认 13420）
  TG_BOT_TOKEN    可选  Telegram 通知
  TG_CHAT_ID      可选  Telegram 通知
  ALL_PROXY       可选  HTTP 代理地址
"""

import os
import re
import time
import json
import requests
from datetime import datetime, timezone

# ===== 配置 =====
COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
SERVER_ID = os.environ.get("SERVER_ID") or "13420"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""

BASE_URL = "https://dash.zampto.net"

# ===== Telegram 通知 =====
def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        return
    try:
        prox = {"http": PROXY, "https": PROXY} if PROXY else None
        local_time = time.gmtime(time.time() + 8 * 3600)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} Zampto 续期\n\n{msg}\n⏱️ {ts}"},
            timeout=15, proxies=prox,
        )
    except Exception:
        pass

def log(msg):
    local_time = time.gmtime(time.time() + 8 * 3600)
    ts = time.strftime("%H:%M:%S", local_time)
    print(f"[{ts}] {msg}", flush=True)

# ===== 创建 API Session =====
def create_api_session():
    """从 ZAMTO_COOKIE 创建 requests.Session"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    if PROXY:
        s.proxies.update({"http": PROXY, "https": PROXY})
        log(f"📌 代理: {PROXY}")

    # 注入 Cookie
    if COOKIE_STR:
        for pair in COOKIE_STR.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name, value = name.strip(), value.strip()
            s.cookies.set(name, value, domain=".zampto.net", path="/")

    return s

# ===== 刷新 CSRF Token =====
def refresh_csrf(api_session):
    """从 Set-Cookie 头中获取最新的 zampto_csrf token"""
    try:
        # 访问任意 API 端点触发 Set-Cookie
        r = api_session.get(f"{BASE_URL}/api/servers", timeout=10)
        log(f"  CSRF 刷新: GET /api/servers → {r.status_code}")

        # 直接从 Set-Cookie 头读取
        set_cookies = []
        try:
            set_cookies = r.raw.headers.getlist("Set-Cookie")
        except (AttributeError, KeyError):
            if "Set-Cookie" in r.headers:
                set_cookies = [r.headers["Set-Cookie"]]

        for sc in set_cookies:
            if "zampto_csrf=" in sc.lower():
                idx = sc.lower().index("zampto_csrf=") + len("zampto_csrf=")
                rest = sc[idx:]
                end = rest.find(";")
                token = rest if end == -1 else rest[:end]
                token = token.strip()
                if token:
                    log(f"  ✅ CSRF 刷新成功 (长度={len(token)})")
                    # 更新 session 中的 cookie
                    api_session.cookies.set("zampto_csrf", token, domain=".zampto.net", path="/")
                    return token

        # 回退: 从 session.cookies 读取
        for c in api_session.cookies:
            if "csrf" in c.name.lower():
                log(f"  ✅ CSRF 从 session.cookies (长度={len(c.value)})")
                return c.value

        log("  ⚠️ 未找到 CSRF cookie")
        return None
    except Exception as e:
        log(f"  ⚠️ CSRF 刷新失败: {e}")
        return None

# ===== 获取服务器信息 =====
def get_server_info(api_session):
    """获取服务器状态信息"""
    info = {"status": "unknown", "expiry": None, "last_renewed": None}

    # 尝试多个 API 路径获取服务器信息
    paths = [
        f"/api/servers",
        f"/api/server",
        f"/api/server/{SERVER_ID}",
        f"/api/servers/{SERVER_ID}",
    ]

    for path in paths:
        try:
            url = f"{BASE_URL}{path}"
            r = api_session.get(url, timeout=15)
            ct = r.headers.get("content-type", "")
            is_json = "json" in ct.lower()

            log(f"  GET {path} → {r.status_code} {'JSON' if is_json else 'HTML'}")

            if r.status_code == 200 and is_json:
                data = r.json()
                log(f"  数据: {json.dumps(data, ensure_ascii=False)[:300]}")

                # 解析服务器列表
                servers = []
                if isinstance(data, dict):
                    if "servers" in data:
                        servers = data["servers"]
                    elif "data" in data:
                        d = data["data"]
                        servers = d if isinstance(d, list) else [d]
                    else:
                        servers = [data]

                # 根据 SERVER_ID 查找
                for sv in servers:
                    sv_id = str(sv.get("id", ""))
                    if sv_id == str(SERVER_ID):
                        info["status"] = sv.get("status", "unknown")
                        info["expiry"] = sv.get("expiry")
                        info["last_renewed"] = sv.get("last_renewed")
                        log(f"  ✅ 找到服务器 {SERVER_ID}: status={info['status']}")
                        return info

                # 如果没找到匹配的，但只有一台服务器就默认用第一台
                if len(servers) == 1:
                    sv = servers[0]
                    info["status"] = sv.get("status", "unknown")
                    info["expiry"] = sv.get("expiry")
                    info["last_renewed"] = sv.get("last_renewed")
                    log(f"  ✅ 使用唯一服务器: status={info['status']}")
                    return info

                log(f"  ⚠️ 在 {path} 中未找到服务器 {SERVER_ID}")

        except Exception as e:
            log(f"  ⚠️ GET {path} 失败: {e}")

    return info

# ===== 续期 =====
def renew_server(api_session):
    """通过 API 续期服务器"""
    log("=" * 40)
    log("🔄 开始 API 续期...")
    log("=" * 40)

    # 1. 刷新 CSRF
    csrf = refresh_csrf(api_session)
    if not csrf:
        log("❌ 无法获取 CSRF token")
        return False

    # 2. 获取服务器信息
    log("📋 获取服务器信息...")
    server_info = get_server_info(api_session)
    log(f"📋 状态: {server_info['status']}")
    log(f"📋 到期: {server_info['expiry']}")
    log(f"📋 上次续期: {server_info['last_renewed']}")

    # 3. 尝试续期
    renew_url = f"{BASE_URL}/api/server/renew"
    log(f"📌 续期 URL: {renew_url}")

    # 尝试多种 body 格式
    body_variants = [
        {"server_id": int(SERVER_ID)},
        {"id": int(SERVER_ID)},
        {"serverId": int(SERVER_ID)},
        {"server": int(SERVER_ID)},
        {"sid": int(SERVER_ID)},
        {"server_id": SERVER_ID},
        {"id": SERVER_ID},
    ]

    for i, body in enumerate(body_variants):
        try:
            # 每次 POST 前刷新 CSRF
            fresh_csrf = refresh_csrf(api_session)
            if not fresh_csrf:
                continue

            log(f"  🔄 尝试 [{i+1}/{len(body_variants)}]: POST /api/server/renew body={body}")

            r = api_session.post(
                renew_url,
                json=body,
                timeout=15,
                headers={"X-CSRF-Token": fresh_csrf},
            )

            ct = r.headers.get("content-type", "")
            is_json = "json" in ct.lower()
            response_preview = r.text[:200] if r.text else "(empty)"

            log(f"  → {r.status_code} {'JSON' if is_json else 'HTML'}: {response_preview}")

            if r.status_code in [200, 201, 204, 202]:
                log("🎉 续期成功！")
                return True

            # 如果返回 captcha/验证 要求，说明需要 Turnstile
            if "captcha" in r.text.lower() or "verification" in r.text.lower() or "turnstile" in r.text.lower():
                log("  ⚠️ API 需要 Turnstile 验证")
                # 尝试服务器启动端点（也许续期 API 需要先启动）
                break

        except Exception as e:
            log(f"  ⚠️ 请求失败: {e}")

    # 4. 如果续期失败，尝试服务器启动 + 续期
    log("=" * 40)
    log("🔄 尝试先启动服务器再续期...")
    log("=" * 40)

    # 尝试启动服务器
    start_paths = [
        f"/api/servers/{SERVER_ID}/start",
        f"/api/server/{SERVER_ID}/start",
        f"/api/server/start",
        f"/api/server/{SERVER_ID}/power",
    ]

    for start_path in start_paths:
        try:
            fresh_csrf = refresh_csrf(api_session)
            if not fresh_csrf:
                continue

            start_url = f"{BASE_URL}{start_path}"
            log(f"  🔄 尝试启动: {start_path}")

            r = api_session.post(
                start_url,
                json={"signal": "start"},
                timeout=15,
                headers={"X-CSRF-Token": fresh_csrf},
            )
            log(f"  → {r.status_code}: {r.text[:100]}")

            if r.status_code in [200, 201, 204, 202]:
                log("  ✅ 服务器启动成功！等待 5 秒...")
                time.sleep(5)
                break
        except Exception as e:
            log(f"  ⚠️ 启动失败: {e}")

    # 启动后再尝试续期
    log("=" * 40)
    log("🔄 启动后再次尝试续期...")
    log("=" * 40)

    for i, body in enumerate(body_variants):
        try:
            fresh_csrf = refresh_csrf(api_session)
            if not fresh_csrf:
                continue

            log(f"  🔄 尝试 [{i+1}/{len(body_variants)}]: POST /api/server/renew body={body}")

            r = api_session.post(
                renew_url,
                json=body,
                timeout=15,
                headers={"X-CSRF-Token": fresh_csrf},
            )

            response_preview = r.text[:200] if r.text else "(empty)"
            log(f"  → {r.status_code}: {response_preview}")

            if r.status_code in [200, 201, 204, 202]:
                log("🎉 续期成功！")
                return True

        except Exception as e:
            log(f"  ⚠️ 请求失败: {e}")

    log("❌ 所有续期尝试均失败")
    return False

# ===== 主入口 =====
def main():
    log("=" * 40)
    log("Zampto 自动续期 v4 (纯 API)")
    log("=" * 40)

    if not COOKIE_STR:
        log("❌ 请配置 ZAMTO_COOKIE")
        send_tg("配置缺失，无法续期", "❌")
        return

    # 创建 API session
    api_session = create_api_session()

    # 验证 session
    log("🔍 验证 session...")
    try:
        r = api_session.get(f"{BASE_URL}/auth/login", timeout=10)
        log(f"  GET /auth/login → {r.status_code}")
        if r.status_code == 200 and "antialiased" in r.text[:500]:
            log("✅ Session 验证通过")
        else:
            log("⚠️ Session 可能失效")
            send_tg("Cookie 可能已失效，请重新获取", "⚠️")
    except Exception as e:
        log(f"❌ 验证请求失败: {e}")

    # 续期
    result = renew_server(api_session)

    if result:
        log("=" * 40)
        log("✅ 续期流程完成")
        log("=" * 40)
        send_tg("续期成功 ✅", "✅")
    else:
        log("=" * 40)
        log("❌ 续期失败")
        send_tg("续期失败，请检查服务器状态", "❌")
        log("=" * 40)


if __name__ == "__main__":
    main()