#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v5.2
修复:
  1. API登录: 用 zampto_csrf cookie 作为CSRF token, 多字段名重试, 打印响应体调试
  2. Turnstile: 移除不支持的 timeout 参数
  3. 浏览器登录: 提交后等待更久, 处理SPA跳转
"""
import os, time, json, re
import requests
from seleniumbase import SB

EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("SERVER_ID", "13420")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("ALL_PROXY") or ""
BASE_URL = "https://dash.zampto.net"
_shot = 0


def log(m):
    ts = time.strftime("%H:%M:%S", time.gmtime(time.time() + 28800))
    print(f"[{ts}] {m}", flush=True)


def shot(sb, t):
    global _shot
    _shot += 1
    try:
        sb.save_screenshot(f"{_shot:02d}_{t}.png")
        log(f"📸{_shot:02d}_{t}")
    except:
        pass


def send_tg(m, i="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{i} Zampto\n\n{m}"},
            timeout=15,
        )
    except:
        pass


def proxy_dict():
    return {"http": PROXY, "https": PROXY} if PROXY else None


def innerText(sb):
    try:
        return sb.execute_script("return document.body.innerText||''") or ""
    except:
        return ""


def get_url(sb):
    try:
        return sb.get_current_url()
    except:
        return ""


def page_source(sb):
    try:
        return sb.get_page_source() or ""
    except:
        return ""


def wait_page(sb, t=20):
    st = time.time()
    while time.time() - st < t:
        u = get_url(sb)
        txt = innerText(sb)
        if len(txt) > 150:
            return True
        if u and "chrome://" in u:
            time.sleep(2)
            continue
        time.sleep(1)
    return False


def nav(sb, u, t=20):
    log(f"🌐 {u}")
    for _ in range(3):
        try:
            sb.open(u)
        except Exception as e:
            log(f"⚠️{e}")
            time.sleep(3)
            continue
        if wait_page(sb, t):
            return True
    log(f"⚠️{get_url(sb)}")
    shot(sb, "nav")
    time.sleep(5)
    return False


def find_btn(sb):
    for sel in ['button:contains("Renew")', 'button:contains("Extend")', 'button:contains("续期")']:
        try:
            es = sb.find_elements(sel)
            if es:
                for e in es:
                    t = (e.text or "").strip()
                    if t and ("renew" in t.lower() or "extend" in t.lower() or "续期" in t):
                        log(f"✅ CSS: '{t}'")
                        return e
        except:
            continue
    try:
        for b in sb.find_elements("button"):
            t = (b.text or "").strip()
            if t and ("renew" in t.lower() or "extend" in t.lower() or "续期" in t):
                log(f"✅ 遍历: '{t}'")
                return b
    except:
        pass
    try:
        btn = sb.execute_script("""
            var els=document.querySelectorAll('button, a, div[role=button], span, input[type=submit]');
            for(var e of els){
                var t=(e.innerText||e.textContent||e.value||'').trim().toLowerCase();
                if(t.includes('renew')||t.includes('extend')||t.includes('续期'))return e;
            }
            return null;
        """)
        if btn:
            log("✅ JS 找到")
            return btn
    except:
        pass
    return None


def api_login():
    """API登录 - 多策略尝试"""
    log("🔐 API登录...")
    prox = proxy_dict()
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    if prox:
        sess.proxies = prox

    # === 策略1: 获取登录页, 提取CSRF, 带CSRF POST ===
    log("📄 获取登录页...")
    r = sess.get(f"{BASE_URL}/auth/login", timeout=15, allow_redirects=True)
    html = r.text
    cookies = sess.cookies.get_dict()
    log(f"  GET HTTP {r.status_code}, cookies({len(cookies)}): {list(cookies.keys())[:5]}")

    # 从cookie获取CSRF
    csrf_from_cookie = cookies.get("zampto_csrf", "") or cookies.get("_token", "") or cookies.get("csrf_token", "") or ""
    log(f"  Cookie CSRF: {'✅ '+csrf_from_cookie[:20]+'...' if csrf_from_cookie else '❌'}")

    # 从HTML提取CSRF
    csrf_token = None
    for pattern in [r'name="_token"\s*value="([^"]+)"',
                    r'name="__csrf_token__"\s*value="([^"]+)"',
                    r'name="csrf_token"\s*value="([^"]+)"',
                    r'name="csrf"\s*value="([^"]+)"']:
        m = re.search(pattern, html)
        if m:
            csrf_token = m.group(1)
            log(f"  HTML CSRF: ✅ {csrf_token[:20]}...")
            break
    if not csrf_token:
        csrf_token = csrf_from_cookie

    # 尝试多个CSRF字段名
    csrf_fields = ["_token", "__csrf_token__", "csrf_token", "csrf", "_token"]
    if not csrf_token:
        csrf_fields = []  # 无CSRF

    for csrf_field in csrf_fields:
        login_data = {"email": EMAIL, "password": PASSWORD}
        if csrf_token:
            login_data[csrf_field] = csrf_token
            log(f"📤 POST with {csrf_field}={csrf_token[:16]}...")
        else:
            log(f"📤 POST without CSRF...")

        r = sess.post(f"{BASE_URL}/auth/login", data=login_data, timeout=15, allow_redirects=True)
        cookies = sess.cookies.get_dict()
        has_session = any("session" in k.lower() for k in cookies.keys())
        logged_in = "/auth/login" not in r.url and "/login" not in r.url
        log(f"    HTTP {r.status_code} | URL: {r.url} | session: {'✅' if has_session else '❌'} | logged: {'✅' if logged_in else '❌'}")

        if has_session or logged_in:
            log(f"✅ API登录成功 (session={has_session}, url={logged_in})")
            return sess

        # 打印响应体调试
        body = r.text[:300]
        log(f"    响应体: {body[:200]}")

    # === 策略2: JSON POST 到API端点 ===
    for endpoint, body in [
        ("/api/v1/login", json.dumps({"email": EMAIL, "password": PASSWORD})),
        ("/api/auth/login", json.dumps({"email": EMAIL, "password": PASSWORD})),
        ("/api/login", json.dumps({"email": EMAIL, "password": PASSWORD})),
    ]:
        log(f"📤 {endpoint} (JSON)...")
        r = sess.post(
            f"{BASE_URL}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        log(f"    HTTP {r.status_code}")
        if r.status_code == 200:
            cookies = sess.cookies.get_dict()
            has_session = any("session" in k.lower() for k in cookies.keys())
            if has_session:
                log(f"  ✅ {endpoint} 成功")
                return sess
            try:
                data = r.json()
                log(f"  响应: {json.dumps(data)[:200]}")
            except:
                log(f"  响应: {r.text[:200]}")

    # === 策略3: 带CSRF的JSON ===
    if csrf_token:
        for endpoint in ["/api/v1/login", "/api/auth/login"]:
            log(f"📤 {endpoint} (JSON+CSRF)...")
            body = {"email": EMAIL, "password": PASSWORD, "_token": csrf_token}
            r = sess.post(
                f"{BASE_URL}{endpoint}",
                data=json.dumps(body),
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            log(f"    HTTP {r.status_code}")
            if r.status_code == 200:
                cookies = sess.cookies.get_dict()
                has_session = any("session" in k.lower() for k in cookies.keys())
                if has_session:
                    log(f"  ✅ {endpoint}+CSRF 成功")
                    return sess

    log("❌ 所有API登录均失败")
    return None


def browser_login(sb):
    """浏览器登录(降级)"""
    log("🌐 浏览器登录...")
    if not nav(sb, f"{BASE_URL}/auth/login", 25):
        return False
    time.sleep(3)

    # 保存页面源码调试
    try:
        src = page_source(sb)
        log(f"  页面源码: {len(src)} 字符")
        # 查找表单结构
        forms = re.findall(r'<form[^>]*>', src)
        if forms:
            for f in forms:
                log(f"  表单: {f[:200]}")
    except:
        pass

    # 等待表单
    try:
        sb.wait_for_element('input[name="email"], input[type="email"]', timeout=10)
        log("✅ 找到登录表单")
    except:
        log(f"⚠️ 未找到表单: {innerText(sb)[:200]}")
        shot(sb, "no_form")
        return False

    # 填写
    try:
        sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
        sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
        log("✅ 已填写")
    except Exception as e:
        log(f"⚠️ 填写失败: {e}")
        return False
    time.sleep(2)

    # 处理Turnstile - 无timeout参数
    try:
        sb.uc_gui_click_captcha()
        time.sleep(4)
        log("✅ Turnstile 已处理")
    except Exception as e:
        log(f"⚠️ Turnstile: {e} (继续...)")

    # 提交
    try:
        sb.click('button[type="submit"]', timeout=5)
        log("✅ 已点击提交")
    except:
        try:
            sb.execute_script("document.querySelector('form')?.submit()")
            log("✅ 已JS提交")
        except Exception as e:
            log(f"⚠️ 提交失败: {e}")

    # 等待跳转
    time.sleep(8)

    u = get_url(sb)
    tx = innerText(sb).lower()
    log(f"📌 {u} ({len(tx)}c)")

    # 检查是否在dashboard
    if any(k in tx for k in ["dashboard", "服务器", "server", "expire", "renew", "dashboard"]):
        log("✅ 登录成功(在dashboard)")
        return True

    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 仍在登录页")
        shot(sb, "login_fail")
        # 打印页面上所有按钮文本
        try:
            btns = sb.execute_script("""
                var btns=document.querySelectorAll('button, input[type=submit], a');
                var result=[];
                btns.forEach(b=>result.push((b.innerText||b.value||b.textContent||'').trim()));
                return result.join('\\n');
            """)
            log(f"  按钮: {btns[:300]}")
        except:
            pass
        return False

    log("✅ 登录成功")
    return True


def main():
    log("=" * 40)
    log("Zampto 续期 v5.2")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")

    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies=proxy_dict(), timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理不可用")

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    # ===== 登录 =====
    api_sess = api_login()
    use_cookies = None
    if api_sess:
        use_cookies = api_sess.cookies.get_dict()
        log(f"✅ 获取到 {len(use_cookies)} 个cookie")
    else:
        log("⚠️ 降级到浏览器登录...")

    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            if not nav(sb, BASE_URL, 25):
                log("❌ 首页打不开")
                send_tg("首页打不开", "❌")
                return
            time.sleep(2)

            if use_cookies:
                log("🍪 注入cookie...")
                for name, value in use_cookies.items():
                    try:
                        sb.add_cookie({"name": name, "value": value, "domain": ".zampto.net", "path": "/"})
                        log(f"  ✅ {name}")
                    except:
                        try:
                            sb.add_cookie({"name": name, "value": value, "domain": "dash.zampto.net", "path": "/"})
                            log(f"  ✅ {name}(dash)")
                        except Exception as e:
                            log(f"  ⚠️ {name}: {e}")
                sb.refresh()
                time.sleep(3)

            u = get_url(sb)
            tx = innerText(sb).lower()
            log(f"📌 {u}")

            if "login" in u.lower() or "auth" in u.lower():
                log("⚠️ 未登录，浏览器登录...")
                if not browser_login(sb):
                    log("❌ 登录彻底失败")
                    shot(sb, "final_fail")
                    send_tg("登录失败，无法续期", "❌")
                    return
                time.sleep(3)

            log("✅ 已登录")
            shot(sb, "logged_in")

            # ===== 续期 =====
            u = f"{BASE_URL}/server?id={SERVER_ID}"
            if not nav(sb, u, 25):
                return
            shot(sb, "server")
            time.sleep(5)

            tx = innerText(sb)
            try:
                log(f"📄 标题: {sb.get_page_title()}")
            except:
                pass
            log(f"📄 {tx[:400]}")

            btn = find_btn(sb)
            if not btn:
                log("❌ 未找到续期按钮")
                log(f"内容: {tx[:800]}")
                # 打印所有按钮文本
                try:
                    btns = sb.execute_script("""
                        var btns=document.querySelectorAll('button, a, div[role=button], input, span');
                        var result=[];
                        btns.forEach(b=>result.push((b.innerText||b.textContent||b.value||'').trim()));
                        return result.join('\\n');
                    """)
                    log(f"所有可点击元素: {btns[:500]}")
                except:
                    pass
                return

            log("🖱️ 点击续期...")
            try:
                sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(1)
                sb.execute_script("arguments[0].click()", btn)
                log("✅ 点击成功")
            except Exception as e:
                log(f"⚠️ JS点击: {e}")
                try:
                    btn.click()
                except:
                    pass
            time.sleep(5)

            shot(sb, "clicked")
            tl = innerText(sb).lower()

            if "security verification" in tl or "complete the security" in tl or "verify you are human" in tl:
                log("🔐 处理弹窗...")
                try:
                    sb.uc_gui_click_captcha()
                    time.sleep(5)
                except:
                    pass
                try:
                    sb.click('button:contains("Confirm"), button:contains("Continue"), button:contains("Yes")', timeout=5)
                except:
                    pass
                time.sleep(3)

            tx = innerText(sb)
            for l in tx.split("\n"):
                l = l.strip()
                if any(k in l.lower() for k in ["last renewed", "just renewed", "renewed", "expire", "expiry"]):
                    log(f"📋 {l}")
            shot(sb, "result")
            log("🎉 续期完成")
            send_tg("续期完成", "✅")

    except Exception as e:
        import traceback
        log(f"💥 {e}")
        log(traceback.format_exc()[:500])
        send_tg(f"异常: {e}", "💥")


if __name__ == "__main__":
    main()