#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 v2 - 纯 API 方式（参考 weikkadd/zampto）

策略:
  1. 从 ZAMTO_COOKIE 读取 session cookie
  2. 用 requests.Session 直接调 API 续期，无需浏览器
  3. 通过代理（NODE_LINK）避免数据中心 IP 被 Cloudflare 拦
  4. 动态刷新 CSRF token

环境变量:
  ZAMTO_COOKIE    必填  Cookie 字符串 "k1=v1; k2=v2"（含 zampto_session + cf_clearance + zampto_csrf）
  ZAMPTO_EMAIL    备选  仅用于通知
  SERVER_ID       可选  服务器 ID（默认 13421）
  TG_BOT_TOKEN    可选  Telegram 通知
  TG_CHAT_ID      可选  Telegram 通知
  ALL_PROXY       可选  HTTP 代理地址
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone

# ===== 配置 =====
COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
EMAIL = os.environ.get("ZAMPTO_EMAIL") or ""
SERVER_ID = os.environ.get("SERVER_ID") or "13421"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""

BASE_URL = "https://dash.zampto.net"

# ===== 日志 =====
def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)

def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        return
    try:
        proxies = {"http": PROXY, "https": PROXY} if PROXY else None
        local_time = time.gmtime(time.time() + 8 * 3600)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} Zampto 续期\n\n{msg}\n⏱️ {ts}"},
            timeout=15, proxies=proxies,
        )
    except Exception as e:
        log(f"⚠️ TG 发送失败: {e}")

# ===== Cookie 解析 =====
def parse_cookies(cookie_str):
    """解析 "k1=v1; k2=v2" 格式的 cookie 字符串"""
    cookies = {}
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        cookies[name.strip()] = value.strip()
    return cookies

def build_session():
    """用 cookie 创建 requests.Session，挂代理"""
    session = requests.Session()
    
    # 挂代理
    if PROXY:
        session.proxies = {"http": PROXY, "https": PROXY}
        log(f"🌐 使用代理: {PROXY}")
    else:
        log("🌐 直连")
    
    # 注入 cookie
    cookies = parse_cookies(COOKIE_STR)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".zampto.net", path="/")
    log(f"🍪 已注入 {len(cookies)} 个 cookie")
    
    # 设置浏览器风格 headers
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })
    
    return session, cookies

def refresh_csrf(session):
    """从 Set-Cookie 头刷新 CSRF token"""
    try:
        r = session.get(f"{BASE_URL}/api/servers", timeout=10)
        # 从 Set-Cookie 提取 zampto_csrf
        for cookie_header in r.raw.headers.getlist("Set-Cookie") if hasattr(r.raw.headers, 'getlist') else [r.headers.get("Set-Cookie", "")]:
            if "zampto_csrf=" in cookie_header:
                val = cookie_header.split("zampto_csrf=")[1].split(";")[0].strip()
                if val:
                    session.cookies.set("zampto_csrf", val, domain=".zampto.net", path="/")
                    return val
        # 兜底：从 session.cookies 获取
        for c in session.cookies:
            if "csrf" in c.name.lower():
                return c.value
    except Exception as e:
        log(f"⚠️ CSRF 刷新失败: {e}")
    return None

# ===== 服务器信息 =====
def get_server_info(session):
    """获取服务器状态和到期时间"""
    paths = [
        f"/api/server/{SERVER_ID}",
        f"/api/servers/{SERVER_ID}",
        "/api/servers",
        f"/api/server?id={SERVER_ID}",
    ]
    for path in paths:
        try:
            r = session.get(f"{BASE_URL}{path}", timeout=15)
            if r.status_code == 200:
                try:
                    data = r.json()
                    log(f"  {path} -> 200 OK")
                    # 处理返回格式
                    if isinstance(data, dict):
                        if "servers" in data:
                            # 列表模式 - 找匹配的服务器
                            for srv in data["servers"]:
                                if str(srv.get("id")) == str(SERVER_ID):
                                    return srv
                            # 没找到匹配 ID，用第一个
                            if data["servers"]:
                                srv = data["servers"][0]
                                log(f"  ⚠️ 未找到 SERVER_ID={SERVER_ID}，使用第一个: id={srv.get('id')} name={srv.get('name')}")
                                return srv
                        elif "data" in data:
                            return data["data"]
                        else:
                            return data
                    return data
                except Exception:
                    continue
            elif r.status_code == 403:
                log(f"  {path} -> 403 (IP 被拦)")
            else:
                log(f"  {path} -> {r.status_code}")
        except Exception as e:
            log(f"  {path} -> 异常: {e}")
    return None

# ===== 续期 =====
def renew_server(session):
    """调用续期 API"""
    log("🔄 尝试续期...")
    
    # 先刷新 CSRF
    csrf = refresh_csrf(session)
    if not csrf:
        log("⚠️ 无法获取 CSRF token，仍尝试续期")
    
    # 尝试多种路径和 body 格式
    # 参考 weikkadd/zampto: POST /api/server/{id}/renew
    path_variants = [
        f"/api/server/{SERVER_ID}/renew",
        f"/api/servers/{SERVER_ID}/renew",
        f"/api/server/renew",
        f"/api/servers/renew",
    ]
    body_variants = [
        {},
        {"server_id": SERVER_ID},
        {"server_id": int(SERVER_ID)},
        {"id": SERVER_ID},
        {"id": int(SERVER_ID)},
        {"serverId": SERVER_ID},
        {"server": SERVER_ID},
    ]
    
    for path in path_variants:
        for body in body_variants:
            try:
                renew_url = f"{BASE_URL}{path}"
                # 每次 POST 前刷新 CSRF
                fresh_csrf = refresh_csrf(session) or csrf
                headers = {"X-CSRF-Token": fresh_csrf} if fresh_csrf else {}
                
                r = session.post(renew_url, json=body, timeout=15, headers=headers)
                skip = body.get("server_id", body.get("id", body.get("server", "{}")))
                log(f"  POST {path} body={body} -> {r.status_code}")
                
                if r.status_code in [200, 201, 202, 204]:
                    try:
                        resp = r.json()
                        log(f"  ✅ 响应: {json.dumps(resp, ensure_ascii=False)[:200]}")
                    except Exception:
                        log(f"  ✅ 响应: {r.text[:200]}")
                    return True
                
                # 检查是否需要 captcha
                if "captcha" in r.text.lower() or "verification" in r.text.lower():
                    log(f"  ❌ 需要 captcha: {r.text[:200]}")
                    continue  # 换个路径试试
                    
            except Exception as e:
                log(f"  {path} body={body} 异常: {e}")
    
    log("❌ 所有组合均失败")
    return False

# ===== 主入口 =====
def main():
    log("=" * 40)
    log("Zampto 自动续期 v2 (纯 API)")
    log("=" * 40)
    
    if not COOKIE_STR:
        log("❌ 未配置 ZAMTO_COOKIE！")
        log("请从浏览器复制 cookie 并设置为 GitHub Secret ZAMTO_COOKIE")
        log("格式: zampto_session=xxx; cf_clearance=xxx; zampto_csrf=xxx")
        return
    
    # 1. 创建 session
    session, cookies = build_session()
    
    # 2. 测试 cookie 有效性
    log("🔍 测试 cookie 有效性...")
    try:
        test_r = session.get(f"{BASE_URL}/api/servers", timeout=15)
        log(f"  测试 GET /api/servers -> {test_r.status_code}")
        if test_r.status_code == 403:
            log("⚠️ 403 - IP 被 Cloudflare 拦截，需要代理")
            log("请配置 NODE_LINK 或 ALL_PROXY 环境变量")
        elif test_r.status_code == 200:
            log("✅ Cookie 有效！")
        else:
            log(f"  Cookie 可能已过期: {test_r.text[:200]}")
    except Exception as e:
        log(f"  测试异常: {e}")
    
    # 3. 获取服务器信息
    log(f"🔍 获取服务器 {SERVER_ID} 信息...")
    info = get_server_info(session)
    if info:
        log(f"📋 服务器信息: {json.dumps(info, ensure_ascii=False, indent=2)[:500]}")
        
        # 检查到期时间
        expiry = info.get("expiry") or info.get("renewal") or info.get("expires_at")
        if expiry:
            log(f"📅 到期时间: {expiry}")
            send_tg(f"服务器 {SERVER_ID} 到期时间: {expiry}", "ℹ️")
        
        # 检查状态
        status = info.get("status", "")
        log(f"📊 状态: {status}")
    else:
        log("⚠️ 无法获取服务器信息")
    
    # 4. 续期
    log("🔄 执行续期...")
    result = renew_server(session)
    
    if result:
        log("✅ 续期成功！")
        send_tg(f"服务器 {SERVER_ID} 续期成功 ✅", "✅")
    else:
        log("❌ 续期失败")
        send_tg(f"服务器 {SERVER_ID} 续期失败 ❌", "❌")
    
    log("=" * 40)

if __name__ == "__main__":
    main()