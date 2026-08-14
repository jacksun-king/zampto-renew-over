#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期（GitHub Actions 版）
参考: guanxi660-crypto/zampto-renew-actions + weikkadd/zampto

策略:
  1. 优先用 ZAMTO_COOKIE（cf_clearance + zampto_session）绕过 CF 登录页
  2. 回退邮箱密码登录（SeleniumBase UC 模式）
  3. 通过代理（NODE_LINK）避免数据中心 IP 被拦

环境变量:
  ZAMTO_COOKIE    可选  Cookie 字符串 "k1=v1; k2=v2"，优先登录绕过 CF
  ZAMPTO_EMAIL    必填  登录邮箱
  ZAMPTO_PASSWORD 必填  登录密码
  SERVER_ID       可选  服务器 ID（默认 13421）
  TG_BOT_TOKEN    可选  Telegram 通知
  TG_CHAT_ID      可选  Telegram 通知
  ALL_PROXY       可选  HTTP 代理地址
"""

import os
import re
import time
import json
import requests
from seleniumbase import SB

# ===== 配置 =====
EMAIL = os.environ.get("ZAMPTO_EMAIL") or ""
PASSWORD = os.environ.get("ZAMPTO_PASSWORD") or ""
COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
SERVER_ID = os.environ.get("SERVER_ID") or "13421"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""

BASE_URL = "https://dash.zampto.net"
LOGIN_URL = f"{BASE_URL}/auth/login"
DASHBOARD_URL = f"{BASE_URL}/server?id={SERVER_ID}"

_shot_no = 0

# ===== Telegram 通知 =====
def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        return
    try:
        prox = {"http": PROXY, "https": PROXY} if PROXY else None
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} {msg}", "parse_mode": "HTML"},
            timeout=15, proxies=prox,
        )
    except Exception:
        pass

def shot(sb, tag):
    global _shot_no
    _shot_no += 1
    try:
        sb.save_screenshot(f"{_shot_no:02d}_{tag}.png")
    except Exception:
        pass

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ===== Cookie 登录 =====
def cookie_login(sb) -> bool:
    """注入 ZAMTO_COOKIE 绕过 CF 登录页"""
    if not COOKIE_STR:
        return False
    log("🍪 尝试 ZAMTO_COOKIE 登录...")
    try:
        sb.open(BASE_URL, timeout=30000)
        time.sleep(2)
        domain = BASE_URL.split("//")[1]
        for pair in COOKIE_STR.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            try:
                sb.add_cookie({"name": name.strip(), "value": value.strip(),
                               "domain": domain, "path": "/"})
            except Exception:
                log(f"  ⚠️ cookie 注入失败: {name.strip()}")
        # 直接进 dashboard
        sb.open(DASHBOARD_URL, timeout=30000)
        time.sleep(5)
        cur_url = sb.driver.current_url.lower().rstrip("/")
        # 如果还在登录页则失败
        if "auth" in cur_url or "login" in cur_url or "blocked" in cur_url:
            log("⚠️ cookie 失效或 IP 不匹配，回退邮箱密码登录")
            shot(sb, "cookie_fail")
            return False
        log("✅ cookie 登录成功！")
        shot(sb, "cookie_ok")
        return True
    except Exception as e:
        log(f"⚠️ cookie 登录异常: {e}")
        return False

# ===== 邮箱密码登录 =====
def login(sb) -> bool:
    log(f"🌐 打开登录页: {LOGIN_URL}")
    try:
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=8)
    except Exception:
        sb.open(LOGIN_URL, timeout=30000)
    time.sleep(6)
    shot(sb, "login_page")

    # 等待登录表单
    form_ok = False
    for i in range(30):
        try:
            src = (sb.get_page_source() or "").lower()
        except Exception:
            time.sleep(5)
            continue
        if 'id="email"' in src or 'type="email"' in src:
            form_ok = True
            break
        if "1005" in src or "access denied" in src or "attention required" in src:
            log("🚫 Cloudflare 1005: IP 被屏蔽")
            return False
        # 检测 iframe 尝试点击验证
        try:
            if sb.execute_script("return !!document.querySelector('iframe')"):
                log(f"🖱️ 检测到 iframe，尝试 uc_gui_click_captcha...", notify=False)
                sb.uc_gui_click_captcha()
                time.sleep(4)
        except Exception:
            pass
        if i > 0 and i % 6 == 0 and "just a moment" in src and 'id="email"' not in src:
            log(f"🔄 刷新重试...")
            try:
                sb.refresh_page()
                time.sleep(15)
            except Exception:
                pass
        time.sleep(5)

    if not form_ok:
        log("❌ 150s 内未检测到登录表单")
        shot(sb, "no_form")
        return False

    try:
        sb.find_element("input[id=\"email\"]").clear()
        sb.find_element("input[id=\"email\"]").send_keys(EMAIL)
        sb.find_element("input[id=\"password\"]").clear()
        sb.find_element("input[id=\"password\"]").send_keys(PASSWORD)
        log("📧 填写邮箱/密码")
        time.sleep(2)
        sb.find_element("button[type=\"submit\"]").click()
        log("🖱️ 点击登录")
        time.sleep(5)

        cur_url = sb.driver.current_url.lower().rstrip("/")
        if "auth" not in cur_url and "login" not in cur_url and "blocked" not in cur_url:
            log("✅ 登录成功！")
            return True
        log("❌ 登录失败")
        shot(sb, "login_fail")
        return False
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        shot(sb, "login_exc")
        return False

# ===== 续期 =====
def renew_server(sb) -> bool:
    """点击续期按钮"""
    log(f"🌐 打开服务器页面...")
    try:
        sb.open(DASHBOARD_URL, timeout=30000)
    except Exception:
        pass
    time.sleep(5)

    # 查找续期按钮
    log("🔍 查找 Renew Server 按钮...")
    found = False
    for sel in [
        'button:contains("Renew Server")',
        'button:contains("Renew")',
        'button.w-full.bg-gradient-to-r',
        'button[data-slot="button"]:has(svg)',
    ]:
        try:
            if sb.find_element(sel, timeout=3):
                log(f"  找到按钮: {sel}")
                found = True
                break
        except Exception:
            continue

    if not found:
        # 尝试遍历所有按钮
        try:
            for btn in sb.find_elements("button"):
                txt = (btn.text or "").strip()
                if "renew" in txt.lower():
                    log(f"  找到: {txt}")
                    found = True
                    break
        except Exception:
            pass

    if not found:
        log("❌ 未找到续期按钮，可能未到续期时间")
        shot(sb, "no_renew_btn")
        send_tg("未找到续期按钮，可能未到续期时间", "ℹ️")
        return False

    # 点击
    log("🖱️ 点击续期按钮...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});",
                          sb.find_element('button:contains("Renew")'))
        time.sleep(0.5)
        sb.click('button:contains("Renew")')
    except Exception:
        try:
            sb.click('button:contains("Renew")')
        except Exception as e:
            log(f"❌ 点击失败: {e}")
            return False

    time.sleep(5)

    # 检查结果
    try:
        body = sb.get_text("body") or ""
        if "renewed" in body.lower() or "expir" in body.lower():
            log("✅ 续期操作完成！")
            send_tg("续期操作完成", "✅")
            return True
    except Exception:
        pass

    shot(sb, "renew_done")
    log("✅ 续期按钮已点击")
    send_tg("续期按钮已点击", "✅")
    return True

# ===== 主入口 =====
def main():
    log("=" * 40)
    log("Zampto 自动续期")
    log("=" * 40)

    if not EMAIL or not PASSWORD:
        log("❌ 缺少 ZAMPTO_EMAIL / ZAMPTO_PASSWORD")
        return

    if COOKIE_STR:
        log("🍪 已配置 ZAMTO_COOKIE，将优先使用 cookie 登录")
    else:
        log("ℹ️ 未配置 ZAMTO_COOKIE，将使用邮箱密码登录")

    if PROXY:
        log(f"🌐 使用代理: {PROXY}")
    else:
        log("🌐 直连")

    with SB(uc=True, headless=True, headless2=True) as sb:
        # 1. 优先 cookie 登录
        logged_in = cookie_login(sb)
        # 2. 回退邮箱密码登录
        if not logged_in:
            logged_in = login(sb)
        # 3. 续期
        if logged_in:
            renew_server(sb)
        else:
            log("❌ 登录失败，终止续期")
            send_tg("登录失败，请检查日志", "❌")

if __name__ == "__main__":
    main()