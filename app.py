#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 v5 - SeleniumBase UC 模式 + 纯 API 混合
策略:
  1. 用 ZAMTO_COOKIE（cf_clearance + zampto_session）注入浏览器
  2. 用 SeleniumBase UC 模式 + xvfb 绕过 Cloudflare 检测
  3. 点击续期按钮，用 uc_gui_click_captcha 处理 Turnstile（xvfb 下可用）
  4. 如果浏览器方式失败，降级到纯 API 尝试

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
from seleniumbase import SB
from datetime import datetime, timezone

# ===== 配置 =====
COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
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

def log(msg):
    local_time = time.gmtime(time.time() + 8 * 3600)
    ts = time.strftime("%H:%M:%S", local_time)
    print(f"[{ts}] {msg}", flush=True)

# ===== Cookie 注入 =====
def inject_cookies(sb):
    """注入 ZAMTO_COOKIE 到浏览器"""
    if not COOKIE_STR:
        log("⚠️ 未设置 ZAMTO_COOKIE")
        return False

    log("🍪 注入 ZAMTO_COOKIE...")
    try:
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=8)
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

        sb.uc_open_with_reconnect(DASHBOARD_URL, reconnect_time=8)
        time.sleep(5)

        cur_url = sb.get_current_url()
        log(f"📌 当前 URL: {cur_url}")

        if "login" in cur_url.lower() or "auth" in cur_url.lower():
            log("⚠️ Cookie 登录失败")
            shot(sb, "cookie_fail")
            return False

        log("✅ Cookie 登录成功！")
        shot(sb, "cookie_ok")
        return True

    except Exception as e:
        log(f"⚠️ Cookie 注入异常: {e}")
        return False

# ===== 提取时间戳 =====
def extract_timestamp(text):
    """从文本中提取时间戳"""
    m = re.search(r'(\w{3}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+(?:AM|PM)\s+\w+)', text)
    return m.group(1) if m else ""

# ===== 浏览器续期 =====
def renew_via_browser(sb):
    """在浏览器中点击续期按钮并处理 Turnstile"""
    log(f"🌐 打开服务器详情页: {DASHBOARD_URL}")
    try:
        sb.uc_open_with_reconnect(DASHBOARD_URL, reconnect_time=8)
        time.sleep(5)
    except Exception:
        pass

    shot(sb, "server_page")
    cur_url = sb.get_current_url()
    log(f"📌 当前 URL: {cur_url}")

    if "/server?id=" not in cur_url and "/server/" not in cur_url:
        log("👆 被重定向，尝试点击服务器卡片...")
        try:
            for link in sb.find_elements("a"):
                href = link.get_attribute("href") or ""
                if "/server?" in href.lower() or "/server/" in href.lower():
                    log(f"  ✅ 点击: {href}")
                    sb.execute_script("arguments[0].click()", link)
                    time.sleep(3)
                    break
        except Exception as e:
            log(f"⚠️ 点击失败: {e}")
        cur_url = sb.get_current_url()
        log(f"📌 点击后 URL: {cur_url}")
        if "/server?id=" not in cur_url and "/server/" not in cur_url:
            log("❌ 无法进入服务器详情页")
            return False

    # 提取续期前时间戳
    body = sb.get_text("body") or ""
    expiry_text = ""
    last_renewed_text = ""
    last_renewed_ts = ""
    for line in body.split("\n"):
        l = line.strip()
        if "next renewal" in l.lower() or "expir" in l.lower() or "剩" in l:
            expiry_text = l
        if "last renewed" in l.lower() or "上次续期" in l:
            last_renewed_text = l
            last_renewed_ts = extract_timestamp(l)
    log(f"📋 续期前 - 到期: {expiry_text}")
    log(f"📋 续期前 - 上次续期: {last_renewed_text}")
    if last_renewed_ts:
        log(f"📋 续期前 - 时间戳: {last_renewed_ts}")

    # 查找续期按钮
    log("🔍 查找续期按钮...")
    renew_btn = None
    for sel in [
        'button:contains("Renew Server")',
        'button:contains("Renew")',
        'button:contains("renew")',
        'button:contains("Extend")',
    ]:
        try:
            for elem in sb.find_elements(sel):
                txt = (elem.text or "").strip()
                if "renew" in txt.lower() or "续期" in txt:
                    renew_btn = elem
                    log(f"  找到按钮: '{txt}'")
                    break
            if renew_btn:
                break
        except Exception:
            continue

    if not renew_btn:
        for btn in sb.find_elements("button"):
            txt = (btn.text or "").strip()
            if txt and ("renew" in txt.lower() or "续期" in txt.lower()):
                renew_btn = btn
                log(f"  找到按钮文本: {txt}")
                break

    if not renew_btn:
        log("❌ 未找到续期按钮")
        shot(sb, "no_renew_btn")
        return False

    # 点击续期按钮
    log("🖱️ 点击续期按钮...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", renew_btn)
        time.sleep(1)
        btn_text = (renew_btn.text or "").strip()
        sb.execute_script("arguments[0].click()", renew_btn)
        log(f"  ✅ 已点击 '{btn_text}'")
    except Exception as e:
        log(f"❌ 点击失败: {e}")
        return False

    # 等待续期结果
    log("⏳ 等待续期处理...")
    renewed = False
    new_last_renewed_ts = ""

    for i in range(20):  # 20 * 5 = 100 秒
        time.sleep(5)

        # 检查是否有 Turnstile 弹窗
        try:
            body = (sb.get_text("body") or "").lower()
            if "security verification" in body or "complete the security" in body or "turnstile" in body:
                log(f"⏳ Turnstile 弹窗 (第{i+1}次)...")
                # uc_gui_click_captcha 需要 xvfb 显示
                try:
                    sb.uc_gui_click_captcha()
                    log(f"  ✅ uc_gui_click_captcha 执行")
                    time.sleep(3)
                    # 检查是否已通过
                    body2 = (sb.get_text("body") or "").lower()
                    if "security verification" not in body2:
                        log("  ✅ Turnstile 验证通过！")
                        continue
                except Exception as e:
                    log(f"  ⚠️ uc_gui_click_captcha 失败: {e}")
                continue
        except Exception:
            pass

        # 检查续期后时间
        try:
            body = sb.get_text("body") or ""
            new_ts = ""
            for line in body.split("\n"):
                l = line.strip()
                if "last renewed" in l.lower() or "上次续期" in l:
                    new_ts = extract_timestamp(l)
                    if new_ts:
                        new_last_renewed_ts = new_ts

            if new_last_renewed_ts and new_last_renewed_ts != last_renewed_ts:
                log(f"📋 续期后 - 时间戳: {new_last_renewed_ts} (旧: {last_renewed_ts})")
                log("🎉 续期时间已更新！")
                renewed = True
                break

            if "just renewed" in body.lower() or "successfully renewed" in body.lower():
                log("🎉 检测到续期成功提示")
                renewed = True
                break

            log(f"  ⏳ 第{i+1}次检查: 未更新")

        except Exception:
            pass

    return renewed


# ===== 纯 API 续期（备选） =====
def renew_via_api():
    """纯 API 方式续期（需要 Turnstile token）"""
    log("=" * 40)
    log("🔄 尝试纯 API 续期...")
    log("=" * 40)

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
    })
    if PROXY:
        s.proxies.update({"http": PROXY, "https": PROXY})

    # 注入 Cookie
    for pair in COOKIE_STR.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        s.cookies.set(name.strip(), value.strip(), domain=".zampto.net", path="/")

    # 获取 CSRF token
    try:
        r = s.get(f"{BASE_URL}/api/servers", timeout=10)
        log(f"  GET /api/servers → {r.status_code}")
        # 提取 CSRF
        csrf = ""
        for c in s.cookies:
            if "csrf" in c.name.lower():
                csrf = c.value
                break
        if not csrf:
            # 从 Set-Cookie 头读取
            for sc in r.headers.get_all("Set-Cookie") if hasattr(r.headers, "get_all") else [r.headers.get("Set-Cookie", "")]:
                if "zampto_csrf=" in sc.lower():
                    idx = sc.lower().index("zampto_csrf=") + len("zampto_csrf=")
                    rest = sc[idx:]
                    end = rest.find(";")
                    csrf = rest if end == -1 else rest[:end]
                    csrf = csrf.strip()
                    break
        log(f"  CSRF: {csrf[:20] if csrf else 'none'}...")

        if not csrf:
            log("⚠️ 无法获取 CSRF token")
            return False

        # 尝试续期 API
        body = {"server_id": int(SERVER_ID)}
        log(f"  POST /api/server/renew body={body}")
        r = s.post(
            f"{BASE_URL}/api/server/renew",
            json=body,
            timeout=15,
            headers={"X-CSRF-Token": csrf},
        )
        log(f"  → {r.status_code}: {r.text[:200]}")

        if r.status_code in [200, 201, 204, 202]:
            log("🎉 API 续期成功！")
            return True

        if "captcha" in r.text.lower() or "verification" in r.text.lower():
            log("  ⚠️ API 需要 Turnstile 验证码，无法绕过")
            log("  💡 需要浏览器模式处理 Turnstile")
            return False

        # 继续尝试其他 body 格式
        for body2 in [
            {"server_id": int(SERVER_ID)},
            {"id": int(SERVER_ID)},
            {"serverId": int(SERVER_ID)},
        ]:
            # 重新获取 CSRF
            s.get(f"{BASE_URL}/api/servers", timeout=10)
            for c in s.cookies:
                if "csrf" in c.name.lower():
                    csrf = c.value
                    break
            r = s.post(
                f"{BASE_URL}/api/server/renew",
                json=body2,
                timeout=15,
                headers={"X-CSRF-Token": csrf},
            )
            log(f"  POST body={body2} → {r.status_code}: {r.text[:100]}")
            if r.status_code in [200, 201, 204, 202]:
                log("🎉 API 续期成功！")
                return True

    except Exception as e:
        log(f"⚠️ API 续期失败: {e}")

    return False


# ===== 主入口 =====
def main():
    log("=" * 40)
    log("Zampto 自动续期 v5 (Browser + API Hybrid)")
    log("=" * 40)

    if not COOKIE_STR:
        log("❌ 请配置 ZAMTO_COOKIE")
        send_tg("配置缺失，无法续期", "❌")
        return

    # 先尝试浏览器方式（需要 xvfb）
    result = False
    try:
        log("🚀 启动浏览器模式...")
        log(f"📌 代理: {PROXY or '直连'}")

        with SB(uc=True, headless=False, incognito=False) as sb:
            log("浏览器已启动")

            # 注入 Cookie
            logged_in = inject_cookies(sb)
            if not logged_in:
                log("⚠️ Cookie 登录失败，尝试纯 API 方式")
                result = renew_via_api()
            else:
                # 浏览器续期
                result = renew_via_browser(sb)

                if result:
                    log("✅ 浏览器续期成功！")
                else:
                    log("⚠️ 浏览器续期失败，尝试纯 API 方式")
                    result = renew_via_api()

    except Exception as e:
        log(f"⚠️ 浏览器模式异常: {e}")
        log("⬇️ 降级到纯 API 方式...")
        result = renew_via_api()

    if result:
        log("=" * 40)
        log("✅ 续期完成")
        log("=" * 40)
        send_tg("续期成功 ✅", "✅")
    else:
        log("=" * 40)
        log("❌ 续期失败")
        log("=" * 40)
        send_tg("续期失败，请检查面板", "❌")


if __name__ == "__main__":
    main()