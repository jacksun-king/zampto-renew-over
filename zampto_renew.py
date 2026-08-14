#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v5.1
修复: API 登录增强(带CSRF/表单重放) + 浏览器登录降级
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
            var els=document.querySelectorAll('button, a, div[role=button], span');
            for(var e of els){
                var t=(e.innerText||e.textContent||'').trim().toLowerCase();
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


def api_login_v2():
    """增强版 API 登录 - 带 CSRF + 表单重放"""
    log("🔐 API 登录(增强)...")
    prox = proxy_dict()
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    if prox:
        sess.proxies = prox

    # Step 1: 访问登录页获取 CSRF token
    log("📄 获取登录页...")
    r = sess.get(f"{BASE_URL}/auth/login", timeout=15, allow_redirects=True)
    log(f"  GET 登录页 HTTP {r.status_code}, cookies: {list(sess.cookies.keys())}")

    # 尝试从页面提取 CSRF token
    csrf_token = None
    html = r.text
    csrf_match = re.search(r'name="_token"\s*value="([^"]+)"', html)
    if csrf_match:
        csrf_token = csrf_match.group(1)
        log(f"  ✅ CSRF: {csrf_token[:16]}...")
    csrf_match2 = re.search(r'name="__csrf_token__"\s*value="([^"]+)"', html)
    if csrf_match2:
        csrf_token = csrf_match2.group(1)
        log(f"  ✅ CSRF2: {csrf_token[:16]}...")

    # Step 2: POST 登录(带CSRF)
    login_data = {"email": EMAIL, "password": PASSWORD}
    if csrf_token:
        login_data["_token"] = csrf_token

    log("📤 POST 登录...")
    r = sess.post(
        f"{BASE_URL}/auth/login",
        data=login_data,
        timeout=15,
        allow_redirects=True,
    )
    log(f"  POST HTTP {r.status_code}, URL: {r.url}")

    cookies = sess.cookies.get_dict()
    log(f"  Cookies({len(cookies)}): {list(cookies.keys())[:10]}")

    # 检查是否登录成功
    has_session = any("session" in k.lower() for k in cookies.keys())
    logged_in = "/auth/login" not in r.url and "/login" not in r.url

    if has_session or logged_in:
        log(f"✅ API 登录成功 (session={'✅' if has_session else '❌'} url={'✅' if logged_in else '❌'})")
        return sess
    else:
        log("⚠️ API 登录被拒")

    # Step 3: 尝试 JSON API 登录
    for endpoint, body_type in [
        ("/api/v1/login", "json"),
        ("/api/auth/login", "data"),
        ("/api/login", "json"),
    ]:
        log(f"  📤 {endpoint}...")
        r2 = sess.post(
            f"{BASE_URL}{endpoint}",
            **({"json": login_data} if body_type == "json" else {"data": login_data}),
            timeout=15,
        )
        log(f"    HTTP {r2.status_code}")
        cookies = sess.cookies.get_dict()
        has_session = any("session" in k.lower() for k in cookies.keys())
        if has_session:
            log(f"  ✅ {endpoint} 成功")
            return sess

    log("❌ 所有 API 登录均失败")
    return None


def browser_login(sb):
    """浏览器直接登录(降级方案)"""
    log("🌐 浏览器登录...")
    if not nav(sb, f"{BASE_URL}/auth/login", 25):
        return False
    time.sleep(3)

    # 等待表单
    try:
        sb.wait_for_element('input[name="email"], input[type="email"]', timeout=10)
        log("✅ 找到登录表单")
    except:
        log(f"⚠️ 未找到表单: {innerText(sb)[:200]}")
        shot(sb, "no_form")
        return False

    # 填写表单
    try:
        sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
        sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
        log("✅ 已填写")
    except Exception as e:
        log(f"⚠️ 填写失败: {e}")
        return False
    time.sleep(2)

    # 处理 Turnstile
    try:
        sb.uc_gui_click_captcha(timeout=8)
        time.sleep(4)
        log("✅ Turnstile 已处理")
    except Exception as e:
        log(f"⚠️ Turnstile: {e} (继续...)")

    # 提交
    try:
        sb.click('button[type="submit"]', timeout=5)
    except:
        try:
            sb.execute_script("document.querySelector('form')?.submit()")
        except:
            pass
    time.sleep(5)

    u = get_url(sb)
    tx = innerText(sb).lower()
    log(f"📌 {u}")
    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 浏览器登录失败")
        shot(sb, "login_fail")
        return False

    log("✅ 浏览器登录成功")
    return True


def main():
    log("=" * 40)
    log("Zampto 续期 v5.1")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")

    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies=proxy_dict(), timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理不可用")

    # 清除 Chrome 的代理环境变量
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    # ===== 登录阶段 =====
    api_sess = api_login_v2()

    if api_sess:
        api_cookies = api_sess.cookies.get_dict()
        log(f"✅ 获取到 {len(api_cookies)} 个 cookie")
        use_cookies = api_cookies
    else:
        log("⚠️ 降级到浏览器登录...")
        use_cookies = None

    # ===== 启动浏览器 =====
    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            # 先访问首页
            if not nav(sb, BASE_URL, 25):
                log("❌ 首页打不开")
                send_tg("首页打不开", "❌")
                return
            time.sleep(2)

            # 注入 cookie（如果有）
            if use_cookies:
                log("🍪 注入 cookie...")
                for name, value in use_cookies.items():
                    try:
                        sb.add_cookie({"name": name, "value": value, "domain": ".zampto.net", "path": "/"})
                        log(f"  ✅ {name}")
                    except Exception:
                        try:
                            sb.add_cookie({"name": name, "value": value, "domain": "dash.zampto.net", "path": "/"})
                            log(f"  ✅ {name}(dash)")
                        except Exception as e:
                            log(f"  ⚠️ {name}: {e}")
                sb.refresh()
                time.sleep(3)

            # 检查是否已登录
            u = get_url(sb)
            tx = innerText(sb).lower()
            log(f"📌 {u}")

            if "login" in u.lower() or "auth" in u.lower():
                log("⚠️ 未登录，尝试浏览器登录...")
                if not browser_login(sb):
                    log("❌ 登录彻底失败")
                    shot(sb, "final_fail")
                    send_tg("登录失败，无法续期", "❌")
                    return
                time.sleep(3)

            log("✅ 已登录")

            # ===== 续期阶段 =====
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
                log(f"内容: {tx[:600]}")
                try:
                    src = sb.get_page_source()
                    with open("page.html", "w") as f:
                        f.write(src)
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

            # 处理安全验证弹窗
            if "security verification" in tl or "complete the security" in tl or "verify you are human" in tl:
                log("🔐 处理弹窗...")
                try:
                    sb.uc_gui_click_captcha(timeout=8)
                    time.sleep(5)
                except:
                    pass
                try:
                    sb.click('button:contains("Confirm"), button:contains("Continue"), button:contains("Yes")', timeout=5)
                except:
                    pass
                time.sleep(3)

            # 检查续期结果
            tx = innerText(sb)
            for l in tx.split("\n"):
                l = l.strip()
                if any(k in l.lower() for k in ["last renewed", "just renewed", "renewed", "expire", "expiry"]):
                    log(f"📋 {l}")
            shot(sb, "result")
            log("🎉 续期完成")
            send_tg("续期完成", "✅")

    except Exception as e:
        log(f"💥 {e}")
        send_tg(f"异常: {e}", "💥")


if __name__ == "__main__":
    main()