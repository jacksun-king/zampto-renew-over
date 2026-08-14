#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 v3 - SeleniumBase UC 模式
参考: akimify/Zampto-Renew + guanxi660-crypto/zampto-renew-actions

策略:
  1. 用 ZAMTO_COOKIE（cf_clearance + zampto_session）注入浏览器
  2. 用 SeleniumBase UC 模式绕过 Cloudflare 检测
  3. 通过代理（NODE_LINK / GOST_PROXY）避免数据中心 IP 被拦
  4. 浏览器打开服务器页面，点击续期按钮

环境变量:
  ZAMTO_COOKIE    必填  Cookie 字符串 "k1=v1; k2=v2"
  ZAMPTO_EMAIL    可选  登录邮箱（备选）
  ZAMPTO_PASSWORD 可选  登录密码（备选）
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
from datetime import datetime, timezone

# ===== 配置 =====
COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
EMAIL = os.environ.get("ZAMPTO_EMAIL") or ""
PASSWORD = os.environ.get("ZAMPTO_PASSWORD") or ""
SERVER_ID = os.environ.get("SERVER_ID") or "13420"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""

BASE_URL = "https://dash.zampto.net"
DASHBOARD_URL = f"{BASE_URL}/server?id={SERVER_ID}"

_shot_no = 0

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

def shot(sb, tag):
    global _shot_no
    _shot_no += 1
    try:
        sb.save_screenshot(f"{_shot_no:02d}_{tag}.png")
    except Exception:
        pass

def log(msg, notify=False):
    local_time = time.gmtime(time.time() + 8 * 3600)
    ts = time.strftime("%H:%M:%S", local_time)
    print(f"[{ts}] {msg}", flush=True)

# ===== Cookie 注入 =====
def inject_cookies(sb):
    """注入 ZAMTO_COOKIE 到浏览器"""
    if not COOKIE_STR:
        log("⚠️ 未设置 ZAMTO_COOKIE，将使用邮箱密码登录")
        return False

    log("🍪 注入 ZAMTO_COOKIE...")
    try:
        # 用 uc_open_with_reconnect 打开页面（处理 Cloudflare 挑战）
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=8)
        time.sleep(3)

        # 检查是否被 Cloudflare 拦
        page_text = sb.get_text("body") or ""
        if "1005" in page_text or "Access denied" in page_text or "Just a moment" in page_text:
            log("⚠️ Cloudflare 拦截，尝试刷新...")
            sb.uc_open_with_reconnect(BASE_URL, reconnect_time=15)
            time.sleep(3)

        for pair in COOKIE_STR.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name, value = name.strip(), value.strip()
            try:
                sb.add_cookie({"name": name, "value": value, "domain": ".zampto.net", "path": "/"})
                log(f"  ✅ {name}")
            except Exception:
                try:
                    sb.add_cookie({"name": name, "value": value, "domain": "dash.zampto.net", "path": "/"})
                    log(f"  ✅ {name} (dash.zampto.net)")
                except Exception as e:
                    log(f"  ⚠️ {name}: {e}")

        # 刷新页面验证
        sb.uc_open_with_reconnect(DASHBOARD_URL, reconnect_time=8)
        time.sleep(5)

        cur_url = sb.get_current_url()
        log(f"📌 当前 URL: {cur_url}")

        if "login" in cur_url.lower() or "auth" in cur_url.lower():
            log("⚠️ Cookie 登录失败，回退邮箱密码登录")
            shot(sb, "cookie_fail")
            return False

        log("✅ Cookie 登录成功！")
        shot(sb, "cookie_ok")
        return True

    except Exception as e:
        log(f"⚠️ Cookie 注入异常: {e}")
        return False

# ===== 邮箱密码登录（备选） =====
def login_with_password(sb):
    """邮箱密码登录（备选方案）"""
    if not EMAIL or not PASSWORD:
        log("❌ 未配置邮箱密码，无法登录")
        return False

    log("🌐 打开登录页...")
    try:
        sb.uc_open_with_reconnect(f"{BASE_URL}/auth/login", reconnect_time=10)
    except Exception:
        pass
    time.sleep(5)

    shot(sb, "login_page")

    # 检测页面内容
    try:
        page_text = (sb.get_text("body") or "").lower()
        page_title = sb.get_page_title() or ""
        log(f"📌 页面标题: {page_title}")
        if "1005" in page_text or "access denied" in page_text:
            log("🚫 Cloudflare 1005: IP 被屏蔽")
            shot(sb, "cf_blocked")
            return False
        if "just a moment" in page_text:
            log("⚠️ Cloudflare 挑战中，等待...")
            time.sleep(10)
    except Exception:
        pass

    # 检查是否有登录表单
    try:
        sb.find_element('input[type="email"], input[name="email"], input[id="email"]', timeout=8)
        log("✅ 找到登录表单")
    except Exception:
        log("⚠️ 未找到登录表单，可能页面未加载完整")
        shot(sb, "no_login_form")
        # 保存页面源码
        try:
            with open("login_page.html", "w") as f:
                f.write(sb.get_page_source())
        except Exception:
            pass
        return False

    # 输入邮箱
    try:
        sb.type('input[type="email"], input[name="email"], input[id="email"]', EMAIL, timeout=5)
        log("✅ 已输入邮箱")
        time.sleep(1)
    except Exception as e:
        log(f"⚠️ 输入邮箱失败: {e}")

    # 输入密码
    try:
        sb.type('input[type="password"], input[name="password"], input[id="password"]', PASSWORD, timeout=5)
        log("✅ 已输入密码")
        time.sleep(1)
    except Exception as e:
        log(f"⚠️ 输入密码失败: {e}")

    # 尝试点击 Turnstile
    time.sleep(2)
    try:
        sb.uc_gui_click_captcha()
        log("🖱️ 已点击 Turnstile 验证")
        time.sleep(3)
    except Exception:
        log("⚠️ Turnstile 点击失败，直接提交")

    # 提交
    try:
        sb.click('button[type="submit"], button:contains("Sign in"), button:contains("Log in"), button:contains("登录")', timeout=10)
        log("✅ 已点击登录按钮")
    except Exception as e:
        log(f"⚠️ 点击登录失败: {e}")
        try:
            sb.execute_script("document.querySelector('button[type=submit]')?.click()")
        except Exception:
            pass

    time.sleep(5)
    shot(sb, "login_done")

    cur_url = sb.get_current_url()
    log(f"📌 登录后 URL: {cur_url}")
    if "login" in cur_url.lower() or "auth" in cur_url.lower():
        log("❌ 登录失败")
        return False
    log("✅ 登录成功！")
    return True

# ===== 续期 =====
def renew_server(sb):
    """在浏览器中点击续期按钮"""
    server_url = f"{BASE_URL}/server?id={SERVER_ID}"
    log(f"🌐 打开服务器详情页: {server_url}")
    try:
        sb.uc_open_with_reconnect(server_url, reconnect_time=8)
        time.sleep(5)
    except Exception:
        pass

    shot(sb, "server_page")
    cur_url = sb.get_current_url()
    log(f"📌 当前 URL: {cur_url}")

    # 如果被重定向到 /servers，说明需要先点服务器卡片
    if "/servers" in cur_url and "id=" not in cur_url:
        log("👆 被重定向到服务器列表，尝试点击服务器卡片...")
        try:
            links = sb.find_elements("a")
            for link in links:
                href = link.get_attribute("href") or ""
                txt = (link.text or "").strip()
                if "/server?id=" in href.lower() or "/server/" in href.lower():
                    log(f"  ✅ 点击服务器: {txt}")
                    sb.execute_script("arguments[0].click()", link)
                    time.sleep(3)
                    break
        except Exception as e:
            log(f"⚠️ 点击服务器卡片失败: {e}")

        shot(sb, "server_page_after_click")
        cur_url = sb.get_current_url()
        log(f"📌 点击后 URL: {cur_url}")

    # 查找续期按钮
    log("🔍 查找续期按钮...")
    found = False
    btn_selectors = [
        'button:contains("Renew Server")',
        'button:contains("Renew")',
        'button:contains("renew")',
        'button:contains("续期")',
        'button:contains("Extend")',
        'button:contains("extend")',
        'button.w-full.bg-gradient-to-r',
        'button[data-slot="button"]:has(svg.lucide-repeat)',
        'button[aria-label*="renew" i]',
        'button[title*="renew" i]',
    ]

    for sel in btn_selectors:
        try:
            if sb.find_element(sel, timeout=3):
                log(f"  找到按钮: {sel}")
                found = True
                break
        except Exception:
            continue

    if not found:
        # 遍历所有按钮
        try:
            for btn in sb.find_elements("button"):
                txt = (btn.text or "").strip()
                if txt and ("renew" in txt.lower() or "续期" in txt or "extend" in txt.lower()):
                    log(f"  找到按钮文本: {txt}")
                    found = True
                    break
        except Exception:
            pass

    if not found:
        log("❌ 未找到续期按钮")
        shot(sb, "no_renew_btn")
        # 保存页面源码分析
        try:
            with open("page_source.html", "w") as f:
                f.write(sb.get_page_source())
        except Exception:
            pass
        # 尝试打印页面可见文本
        try:
            body_text = sb.get_text("body") or ""
            log(f"📄 页面文本片段: {body_text[:300]}")
        except Exception:
            pass
        return False

    # 点击续期
    log("🖱️ 点击续期按钮...")
    try:
        sb.execute_script(
            "arguments[0].scrollIntoView({behavior:'smooth',block:'center'});",
            sb.find_element('button:contains("Renew")')
        )
        time.sleep(1)
        sb.click('button:contains("Renew")')
    except Exception:
        try:
            sb.click('button:contains("Renew")')
        except Exception as e:
            log(f"❌ 点击失败: {e}")
            return False

    time.sleep(5)
    shot(sb, "renew_clicked")

    # 检查结果
    try:
        body = sb.get_text("body") or ""
        if "renewed" in body.lower() or "expir" in body.lower() or "success" in body.lower():
            log("✅ 续期完成！")
            send_tg("续期成功 ✅", "✅")
            return True
    except Exception:
        pass

    log("✅ 续期按钮已点击（等待下次检查确认）")
    send_tg("续期按钮已点击，等待确认", "ℹ️")
    return True

# ===== 主入口 =====
def main():
    log("=" * 40)
    log("Zampto 自动续期 v3 (SeleniumBase UC)")
    log("=" * 40)

    if not COOKIE_STR and (not EMAIL or not PASSWORD):
        log("❌ 请配置 ZAMTO_COOKIE 或 ZAMPTO_EMAIL + ZAMPTO_PASSWORD")
        send_tg("配置缺失，无法续期", "❌")
        return

    with SB(uc=True, headless2=True, incognito=False) as sb:
        log("🚀 浏览器启动")
        log(f"📌 代理: {PROXY or '直连'}")

        # 1. 尝试 Cookie 登录
        logged_in = inject_cookies(sb)

        # 2. 失败则回退邮箱密码
        if not logged_in:
            logged_in = login_with_password(sb)

        if not logged_in:
            log("❌ 登录失败，终止")
            send_tg("登录失败，请检查 Cookie 或账号密码", "❌")
            return

        # 3. 续期
        log("=" * 40)
        result = renew_server(sb)

        if result:
            log("=" * 40)
            log("✅ 续期流程完成")
            log("=" * 40)
        else:
            log("=" * 40)
            log("❌ 续期失败")
            send_tg("续期失败，请检查服务器状态", "❌")
            log("=" * 40)


if __name__ == "__main__":
    main()