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


# ===== Turnstile 处理 =====
def handle_turnstile(sb, max_attempts=15):
    """处理 Turnstile 验证弹窗，尝试多种方法"""
    for i in range(max_attempts):
        time.sleep(5)

        # 检查页面是否还有 Turnstile
        try:
            body = (sb.get_text("body") or "").lower()
            if "security verification" not in body and "complete the security" not in body and "turnstile" not in body:
                log("  ✅ Turnstile 弹窗已消失")
                return True
        except Exception:
            pass

        log(f"⏳ Turnstile 验证弹窗 (第{i+1}次)...")

        # 方法1: uc_gui_click_captcha (不带参数)
        try:
            sb.uc_gui_click_captcha()
            log(f"  ✅ 方法1: uc_gui_click_captcha 执行")
            time.sleep(3)
            body2 = (sb.get_text("body") or "").lower()
            if "security verification" not in body2:
                log("  ✅ Turnstile 验证通过！")
                return True
        except Exception as e:
            log(f"  ⚠️ 方法1失败: {e}")

        # 方法2: 直接点击 Turnstile 的 iframe
        try:
            log("  🔄 方法2: 尝试点击 Turnstile iframe...")
            # 查找 Turnstile iframe
            sb.execute_script("""
                var iframe = document.querySelector('iframe[src*="turnstile"]');
                if (iframe) {
                    iframe.contentDocument.querySelector('#checkbox')?.click();
                    return true;
                }
                // 或者找 cf-turnstile div
                var turnstile = document.querySelector('#cf-turnstile');
                if (turnstile) {
                    // 尝试触发回调
                    turnstile.dispatchEvent(new Event('click'));
                    return true;
                }
                return false;
            """)
            time.sleep(3)
            body2 = (sb.get_text("body") or "").lower()
            if "security verification" not in body2:
                log("  ✅ 方法2: Turnstile 验证通过！")
                return True
        except Exception as e:
            log(f"  ⚠️ 方法2失败: {e}")

        # 方法3: 用 JavaScript 绕开 Turnstile, 直接调 callback
        try:
            log("  🔄 方法3: 尝试直接触发 Turnstile callback...")
            result = sb.execute_script("""
                // 尝试找到 Turnstile 的 callback
                var turnstileDiv = document.querySelector('#cf-turnstile');
                if (turnstileDiv) {
                    var callback = turnstileDiv.getAttribute('data-callback');
                    if (callback && window[callback]) {
                        window[callback]('DUMMY_TOKEN');
                        return 'callback_called: ' + callback;
                    }
                }
                // 尝试 call turnstile.render
                if (typeof turnstile !== 'undefined') {
                    var sitekey = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
                    if (sitekey) {
                        return 'turnstile_available sitekey=' + sitekey;
                    }
                    return 'turnstile_available no_sitekey';
                }
                return 'no_turnstile_found';
            """)
            log(f"  📌 方法3: {result}")
            time.sleep(3)
        except Exception as e:
            log(f"  ⚠️ 方法3失败: {e}")

        # 方法4: 尝试用 pyautogui 直接点击 checkbox 位置
        try:
            log("  🔄 方法4: 尝试 find Turnstile checkbox 坐标...")
            checkbox = sb.execute_script("""
                var iframe = document.querySelector('iframe[src*="turnstile"]');
                if (iframe) {
                    var rect = iframe.getBoundingClientRect();
                    return JSON.stringify({x: rect.left + rect.width/2, y: rect.top + rect.height/2, w: rect.width, h: rect.height});
                }
                var c = document.querySelector('#cf-turnstile');
                if (c) {
                    var rect = c.getBoundingClientRect();
                    return JSON.stringify({x: rect.left + rect.width/2, y: rect.top + rect.height/2, w: rect.width, h: rect.height});
                }
                return 'not_found';
            """)
            log(f"  📌 Turnstile 位置: {checkbox}")
            if checkbox and checkbox != 'not_found':
                try:
                    pos = json.loads(checkbox)
                    import pyautogui
                    pyautogui.click(pos['x'], pos['y'])
                    log("  ✅ 方法4: pyautogui 点击")
                    time.sleep(3)
                except Exception as e2:
                    log(f"  ⚠️ 方法4点击失败: {e2}")
        except Exception as e:
            log(f"  ⚠️ 方法4失败: {e}")

    log("❌ Turnstile 处理超时")
    return False


# ===== 从页面源码中提取 API 端点 =====
def find_api_endpoints(sb):
    """从页面源码中提取 API 端点"""
    endpoints = {}
    try:
        # 获取页面源码（包括 __NEXT_DATA__）
        html = sb.execute_script("return document.documentElement.outerHTML;") or ""
        log(f"📄 页面源码: {len(html)} 字符")

        # 提取 __NEXT_DATA__
        next_data = re.search(r'__NEXT_DATA__[^>]*>(.*?)</script>', html, re.DOTALL)
        if next_data:
            try:
                jdata = json.loads(next_data.group(1))
                jstr = json.dumps(jdata)
                # 查找所有 API 路径
                for m in re.findall(r'["\'](/[a-zA-Z0-9_/.-]+)["\']', jstr):
                    if any(k in m.lower() for k in ['renew', 'api', 'server', 'extend']):
                        endpoints[m] = 'next_data'
                log(f"  📌 从 __NEXT_DATA__ 找到 {len(endpoints)} 个候选端点")
            except Exception as e:
                log(f"  ⚠️ 解析 __NEXT_DATA__ 失败: {e}")

        # 搜索 JS 中的 API 调用
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        for script in scripts:
            for m in re.findall(r'["\'](/[a-zA-Z0-9_/.-]+(?:renew|extend|server)[a-zA-Z0-9_/.-]*)["\']', script):
                endpoints[m] = 'script'
            for m in re.findall(r'["\'](/[a-zA-Z0-9_/.-]*api[a-zA-Z0-9_/.-]*)["\']', script):
                endpoints[m] = 'script'

        # 查找 JS 文件中的 API
        js_src = re.findall(r'<script[^>]*src="([^"]*)"', html)
        for src in js_src[:10]:
            try:
                if src.startswith('/'):
                    full_url = f"{BASE_URL}{src}"
                else:
                    full_url = src
                log(f"  📌 获取 JS: {src[:80]}")
                resp = requests.get(full_url, timeout=5)
                if resp.status_code == 200:
                    js = resp.text
                    for m in re.findall(r'["\'](/[a-zA-Z0-9_/.-]+(?:renew|extend)[a-zA-Z0-9_/.-]*)["\']', js):
                        endpoints[m] = 'js'
            except Exception as e:
                pass

        log(f"📌 找到 {len(endpoints)} 个 API 端点:")
        for ep in sorted(endpoints.keys()):
            log(f"  {ep} ({endpoints[ep]})")

    except Exception as e:
        log(f"⚠️ API 端点提取失败: {e}")

    return list(endpoints.keys())


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
    if "/server?id=" not in cur_url and "/server/" not in cur_url:
        log("👆 被重定向，尝试点击服务器卡片...")
        try:
            links = sb.find_elements("a")
            for link in links:
                href = link.get_attribute("href") or ""
                if "/server?" in href.lower() or "/server/" in href.lower():
                    log(f"  ✅ 点击: {href}")
                    sb.execute_script("arguments[0].click()", link)
                    time.sleep(3)
                    break
        except Exception as e:
            log(f"⚠️ 点击失败: {e}")

        shot(sb, "server_page_after_click")
        cur_url = sb.get_current_url()
        log(f"📌 点击后 URL: {cur_url}")

        if "/server?id=" not in cur_url and "/server/" not in cur_url:
            log("❌ 无法进入服务器详情页")
            return False

    # 提取续期前的到期时间
    expiry_text = ""
    last_renewed_text = ""
    try:
        body = sb.get_text("body") or ""
        for line in body.split("\n"):
            l = line.strip()
            if "next renewal" in l.lower() or "expir" in l.lower() or "剩" in l:
                expiry_text = l
            if "last renewed" in l.lower() or "上次续期" in l:
                last_renewed_text = l
        log(f"📋 续期前 - 到期: {expiry_text}")
        log(f"📋 续期前 - 上次续期: {last_renewed_text}")
    except Exception:
        pass

    # 查找续期按钮
    log("🔍 查找续期按钮...")
    renew_btn = None
    btn_selectors = [
        'button:contains("Renew Server")',
        'button:contains("Renew")',
        'button:contains("renew")',
        'button:contains("续期")',
        'button:contains("Extend")',
        'button:contains("extend")',
        'button.w-full.bg-gradient-to-r',
        'button[data-slot="button"]:has(svg.lucide-repeat)',
    ]

    for sel in btn_selectors:
        try:
            elems = sb.find_elements(sel)
            if elems:
                for elem in elems:
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
        # 遍历所有按钮
        for btn in sb.find_elements("button"):
            txt = (btn.text or "").strip()
            if txt and ("renew" in txt.lower() or "续期" in txt.lower() or "extend" in txt.lower()):
                renew_btn = btn
                log(f"  找到按钮文本: {txt}")
                break

    if not renew_btn:
        log("❌ 未找到续期按钮")
        shot(sb, "no_renew_btn")
        return False

    # ===== 点击续期按钮 =====
    log("🖱️ 点击续期按钮...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", renew_btn)
        time.sleep(1)
        renew_btn_text = (renew_btn.text or "").strip()
        sb.execute_script("arguments[0].click()", renew_btn)
        log(f"  ✅ 已点击 '{renew_btn_text}'")
    except Exception as e:
        log(f"❌ 点击失败: {e}")
        return False

    # ===== 等待续期结果（处理 Turnstile） =====
    log("⏳ 等待续期处理（含 Turnstile 处理）...")
    renewed = False
    new_expiry = ""
    new_last_renewed = ""

    # 先处理 Turnstile（最多 15 次，每次 5 秒 = 75 秒）
    turnstile_ok = handle_turnstile(sb, max_attempts=15)

    # 等待续期完成（再等 30 秒）
    for i in range(6):
        time.sleep(5)

        try:
            body = sb.get_text("body") or ""
            current_url = sb.get_current_url()

            # 找 Last Renewed 时间
            for line in body.split("\n"):
                l = line.strip()
                if "last renewed" in l.lower() or "上次续期" in l:
                    new_last_renewed = l
                if "next renewal" in l.lower() or "expir" in l.lower() or "剩" in l:
                    new_expiry = l

            # 如果 Last Renewed 时间变了，说明续期成功
            if new_last_renewed and new_last_renewed != last_renewed_text:
                log(f"📋 续期后 - 上次续期: {new_last_renewed}")
                log(f"📋 续期后 - 到期: {new_expiry}")
                log("🎉 续期时间已更新！续期成功！")
                renewed = True
                break

            # 如果页面出现 "just renewed" 等提示
            body_lower = body.lower()
            if "just renewed" in body_lower or "successfully renewed" in body_lower:
                log("🎉 检测到续期成功提示")
                renewed = True
                break

            log(f"  ⏳ 第{i+1}次检查: 续期时间未更新 (URL: {current_url})")

        except Exception as e:
            log(f"  ⚠️ 检查异常: {e}")

    # ===== 如果还是没成功，找 API 端点并尝试直接调用 =====
    if not renewed:
        log("=" * 40)
        log("🔍 查找 API 端点并尝试直接调用...")
        log("=" * 40)

        # 从页面源码中提取 API 端点
        api_endpoints = find_api_endpoints(sb)

        # 尝试所有找到的端点
        for api_path in api_endpoints:
            full_url = f"{BASE_URL}{api_path}"
            log(f"  📌 尝试: POST {full_url}")
            try:
                result = sb.execute_script(f"""
                    try {{
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '{api_path}', false);
                        xhr.setRequestHeader('Content-Type', 'application/json');
                        xhr.withCredentials = true;
                        xhr.send();
                        return JSON.stringify({{status: xhr.status, body: (xhr.responseText || '').substring(0, 300)}});
                    }} catch(e) {{
                        return JSON.stringify({{error: e.message}});
                    }}
                """)
                log(f"  → {result}")
                if result and ('"status":200' in result or '"status":201' in result or '"status":204' in result):
                    log("🎉 API 续期成功！")
                    renewed = True
                    time.sleep(3)
                    break
            except Exception as e:
                log(f"  ⚠️ 失败: {e}")

        # 如果 POST 没找到，尝试 GET
        if not renewed:
            for api_path in api_endpoints:
                full_url = f"{BASE_URL}{api_path}"
                log(f"  📌 尝试: GET {full_url}")
                try:
                    result = sb.execute_script(f"""
                        try {{
                            var xhr = new XMLHttpRequest();
                            xhr.open('GET', '{api_path}', false);
                            xhr.withCredentials = true;
                            xhr.send();
                            return JSON.stringify({{status: xhr.status, body: (xhr.responseText || '').substring(0, 300)}});
                        }} catch(e) {{
                            return JSON.stringify({{error: e.message}});
                        }}
                    """)
                    log(f"  → {result}")
                    if result and ('"status":200' in result or '"status":201' in result or '"status":204' in result):
                        log("🎉 API 续期成功！")
                        renewed = True
                        time.sleep(3)
                        break
                except Exception as e:
                    log(f"  ⚠️ 失败: {e}")

    # ===== 最终结果 =====
    if renewed:
        expiry_msg = ""
        try:
            body = sb.get_text("body") or ""
            for line in body.split("\n"):
                l = line.strip()
                if "next renewal" in l.lower() or "expir" in l.lower() or "last renewed" in l.lower() or "剩" in l:
                    expiry_msg += f"\n📌 {l[:80]}"
        except Exception:
            pass

        log("=" * 40)
        log("🎉 续期成功！")
        log("=" * 40)
        send_tg(f"续期成功 ✅{expiry_msg}", "✅")
        return True
    else:
        log("=" * 40)
        log("❌ 续期失败 - 续期时间未更新")
        shot(sb, "renew_fail")

        # 保存页面源码供调试
        try:
            source = sb.execute_script("return document.documentElement.outerHTML;") or ""
            with open("page_source_fail.html", "w") as f:
                f.write(source)
            log("📄 页面源码已保存到 page_source_fail.html")
        except Exception:
            pass

        log("=" * 40)
        send_tg("续期失败，请检查面板", "❌")
        return False


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