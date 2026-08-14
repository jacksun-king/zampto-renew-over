#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 v6 - SeleniumBase UC 模式 + JS Turnstile 处理
策略:
  1. 用 ZAMTO_COOKIE 注入浏览器
  2. 用 SeleniumBase UC 模式 + headless2 绕过 Cloudflare
  3. 点击续期按钮，用 JS 处理 Turnstile（不依赖 PyAutoGUI）
  4. 降级到纯 API

环境变量:
  ZAMTO_COOKIE    必填  Cookie 字符串
  SERVER_ID       可选  服务器 ID（默认 13420）
  TG_BOT_TOKEN    可选  Telegram 通知
  TG_CHAT_ID      可选  Telegram 通知
  ALL_PROXY       可选  HTTP 代理地址
"""

import os, re, time, json, requests
from seleniumbase import SB

COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
SERVER_ID = os.environ.get("SERVER_ID") or "13420"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
BASE_URL = "https://dash.zampto.net"
_shot_no = 0

def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID): return
    try:
        p = {"http": PROXY, "https": PROXY} if PROXY else None
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 8*3600))
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} Zampto 续期\n\n{msg}\n⏱️ {t}"}, timeout=15, proxies=p)
    except: pass

def shot(sb, tag):
    global _shot_no; _shot_no += 1
    try: sb.save_screenshot(f"{_shot_no:02d}_{tag}.png")
    except: pass

def log(msg):
    t = time.strftime("%H:%M:%S", time.gmtime(time.time() + 8*3600))
    print(f"[{t}] {msg}", flush=True)

def extract_ts(text):
    m = re.search(r'(\w{3}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+(?:AM|PM)\s+\w+)', text)
    return m.group(1) if m else ""

def inject_cookies(sb):
    log("🍪 注入 ZAMTO_COOKIE...")
    try:
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=8); time.sleep(3)
        for pair in COOKIE_STR.split(";"):
            pair = pair.strip()
            if "=" not in pair: continue
            n, v = pair.split("=", 1); n, v = n.strip(), v.strip()
            for d in [".zampto.net", "dash.zampto.net"]:
                try:
                    sb.add_cookie({"name": n, "value": v, "domain": d, "path": "/"})
                    break
                except: pass
        sb.uc_open_with_reconnect(f"{BASE_URL}/server?id={SERVER_ID}", reconnect_time=8); time.sleep(5)
        u = sb.get_current_url()
        log(f"📌 URL: {u}")
        if "login" in u.lower() or "auth" in u.lower():
            log("⚠️ Cookie 失效"); return False
        log("✅ Cookie 登录成功！"); return True
    except Exception as e:
        log(f"⚠️ Cookie 注入异常: {e}"); return False

def find_renew_button(sb):
    for sel in ['button:contains("Renew Server")', 'button:contains("Renew")',
                'button:contains("renew")', 'button:contains("Extend")']:
        try:
            for e in sb.find_elements(sel):
                if "renew" in (e.text or "").lower():
                    return e
        except: pass
    for btn in sb.find_elements("button"):
        if "renew" in (btn.text or "").strip().lower():
            return btn
    return None

def handle_turnstile_js(sb):
    """用 JS 处理 Turnstile 弹窗，不依赖 PyAutoGUI"""
    try:
        result = sb.execute_script("""
            // 1. 查找 Turnstile iframe 并点击
            var iframe = document.querySelector('iframe[src*="turnstile"]');
            if (iframe) {
                var r = iframe.getBoundingClientRect();
                var evt = new MouseEvent('click', {bubbles:true, cancelable:true, view:window,
                    clientX: r.left + r.width/2, clientY: r.top + r.height/2});
                iframe.dispatchEvent(evt);
                return 'iframe_clicked';
            }
            // 2. 查找 cf-turnstile div
            var ts = document.querySelector('#cf-turnstile, [data-sitekey]');
            if (ts) {
                ts.click();
                return 'div_clicked';
            }
            // 3. 找 sitekey 并尝试 render
            if (typeof turnstile !== 'undefined') {
                // 搜索所有元素找 sitekey
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var sk = all[i].getAttribute('data-sitekey');
                    if (sk) {
                        turnstile.render(all[i], {
                            sitekey: sk,
                            callback: function(token) {
                                var inp = document.createElement('input');
                                inp.type = 'hidden'; inp.name = 'cf-turnstile-response'; inp.value = token;
                                document.body.appendChild(inp);
                            }
                        });
                        return 'rendered_sk=' + sk;
                    }
                }
                // 尝试从 turnstile 对象获取 sitekey
                if (turnstile._sitekey) return 'sitekey_from_js=' + turnstile._sitekey;
                return 'turnstile_available_no_sitekey';
            }
            // 4. 检查页面是否已有 token
            var token = document.querySelector('[name="cf-turnstile-response"]');
            if (token && token.value) return 'token_exists=' + token.value.substring(0, 20);
            return 'no_turnstile';
        """)
        log(f"  📌 JS: {result}")
        return result
    except Exception as e:
        log(f"  ⚠️ JS 失败: {e}")
        return None

def renew_browser(sb):
    log(f"🌐 打开服务器: {BASE_URL}/server?id={SERVER_ID}")
    try: sb.uc_open_with_reconnect(f"{BASE_URL}/server?id={SERVER_ID}", reconnect_time=8); time.sleep(5)
    except: pass

    # 获取时间戳
    body = sb.get_text("body") or ""
    last_ts = ""
    for l in body.split("\n"):
        if "last renewed" in l.lower() or "上次续期" in l:
            last_ts = extract_ts(l)
            log(f"📋 续期前: {l.strip()}")
    log(f"📋 时间戳: {last_ts or '未找到'}")

    # 找按钮
    btn = find_renew_button(sb)
    if not btn:
        log("❌ 未找到续期按钮")
        # 截图并打印页面片段
        try:
            body_preview = sb.execute_script("return document.body.innerText.substring(0, 500);") or ""
            log(f"📄 页面内容: {body_preview[:200]}")
        except: pass
        return False

    # 点击
    log(f"🖱️ 点击 '{btn.text.strip()}'")
    try:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(1)
        sb.execute_script("arguments[0].click()", btn)
        log("  ✅ 已点击")
    except Exception as e:
        log(f"❌ 点击失败: {e}")
        return False

    # 等待续期
    log("⏳ 等待续期...")
    renewed = False

    for i in range(25):  # 125 秒
        time.sleep(5)

        # 检查 Turnstile
        try:
            body = (sb.get_text("body") or "").lower()
            if "security verification" in body or "turnstile" in body:
                log(f"⏳ Turnstile (第{i+1}次)")
                handle_turnstile_js(sb)
                continue
        except: pass

        # 检查续期结果
        try:
            body = sb.get_text("body") or ""
            new_ts = ""
            for l in body.split("\n"):
                if "last renewed" in l.lower() or "上次续期" in l:
                    new_ts = extract_ts(l)
                    if new_ts and new_ts != last_ts:
                        log(f"📋 续期后: {l.strip()}")
                        log(f"🎉 续期成功! {new_ts}")
                        renewed = True
                    break
            if renewed: break
            if "just renewed" in body.lower() or "successfully renewed" in body.lower():
                log("🎉 续期成功提示"); renewed = True; break
        except: pass

    return renewed

def renew_api():
    log("🔄 尝试纯 API...")
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE_URL}/", "Origin": BASE_URL})
    if PROXY: s.proxies.update({"http": PROXY, "https": PROXY})
    for pair in COOKIE_STR.split(";"):
        if "=" not in pair: continue
        n, v = pair.split("=", 1); s.cookies.set(n.strip(), v.strip(), domain=".zampto.net", path="/")
    try:
        r = s.get(f"{BASE_URL}/api/servers", timeout=10)
        csrf = next((c.value for c in s.cookies if "csrf" in c.name.lower()), "")
        log(f"  CSRF: {csrf[:20] if csrf else 'none'}...")
        r = s.post(f"{BASE_URL}/api/server/renew", json={"server_id": int(SERVER_ID)},
            timeout=15, headers={"X-CSRF-Token": csrf})
        log(f"  → {r.status_code}: {r.text[:200]}")
        if r.status_code in [200, 201, 204, 202]: return True
    except Exception as e:
        log(f"  ⚠️ API 失败: {e}")
    return False

def main():
    log("=" * 40)
    log("Zampto 续期 v6")
    log("=" * 40)
    if not COOKIE_STR: log("❌ 无 Cookie"); send_tg("配置缺失", "❌"); return

    result = False
    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("🚀 浏览器启动")
            if inject_cookies(sb):
                result = renew_browser(sb)
            else:
                log("⚠️ 浏览器登录失败")
    except Exception as e:
        log(f"⚠️ 浏览器异常: {e}")

    if not result:
        log("⬇️ 降级到 API...")
        result = renew_api()

    if result:
        log("✅ 续期成功"); send_tg("续期成功 ✅", "✅")
    else:
        log("❌ 续期失败"); send_tg("续期失败，请检查面板", "❌")

if __name__ == "__main__":
    main()