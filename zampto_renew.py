#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v8.0
修复: 登录入口 auth.zampto.net 已宕机(522), 改回 dash.zampto.net/auth/login
     密码登录优先, 邮箱验证码兜底(Gmail IMAP), 修复 JS 拼接 bug
"""
import os, time, json, re, imaplib, email
import requests
from seleniumbase import SB

# ===== 配置 =====
LOGIN_URL = "https://dash.zampto.net/auth/login"
BASE_URL = "https://dash.zampto.net"
SERVER_ID = os.environ.get("SERVER_ID", "13420")
DASHBOARD_URL = f"{BASE_URL}/server?id={SERVER_ID}"
PROXY = os.environ.get("ALL_PROXY") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
_shot = 0

# 从 ZAMPTO_ACCOUNT (user:pwd) 或单独的 EMAIL/PASSWORD 读取
ZAMPTO_ACCOUNT = os.environ.get("ZAMPTO_ACCOUNT", "")
EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")

if ZAMPTO_ACCOUNT:
    EMAIL, PASSWORD = ZAMPTO_ACCOUNT.split(":", 1)
elif not (EMAIL and PASSWORD):
    raise RuntimeError("未配置 ZAMPTO_EMAIL/PASSWORD 或 ZAMPTO_ACCOUNT")


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


def wait_page(sb, t=25):
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


def nav(sb, u, t=25):
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


def find_and_click(sb, keywords):
    """JS查找包含关键字的按钮并点击 (keywords 经 JSON 传入, 避免拼接 bug)"""
    kw_json = json.dumps(keywords)
    try:
        result = sb.execute_script(f"""
            var kws = {kw_json};
            var btns=document.querySelectorAll('button, a, div[role=button], span, input[type=submit], [data-slot="button"]');
            for(var b of btns){{
                var t=(b.innerText||b.textContent||b.value||'').trim().toLowerCase();
                for(var k of kws){{ if(t.includes(k)) return b; }}
            }}
            return null;
        """)
    except Exception as e:
        log(f"⚠️ find_and_click JS: {e}")
        return False
    if result:
        try:
            sb.execute_script("arguments[0].scrollIntoView({block:'center'});", result)
            time.sleep(0.5)
            sb.execute_script("arguments[0].click()", result)
            log("✅ 点击成功")
            return True
        except Exception as e:
            log(f"⚠️ 点击失败: {e}")
    return False


def handle_turnstile(sb):
    """尝试处理页面上的 Cloudflare Turnstile"""
    try:
        if sb.is_element_present('iframe[title*="Cloudflare"], iframe[src*="challenge"], iframe[src*="turnstile"]'):
            log("🔐 发现Turnstile, 尝试点击...")
            sb.uc_gui_click_captcha()
            time.sleep(3)
            return True
    except:
        pass
    return False


def get_verification_code():
    """从Gmail读取最新验证码"""
    log("📧 连接Gmail IMAP...")
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(EMAIL, GMAIL_APP_PASSWORD)
        log("✅ Gmail登录成功")
    except Exception as e:
        log(f"❌ Gmail登录失败: {e}")
        return None

    for attempt in range(8):
        log(f"📧 搜索验证码邮件 (尝试 {attempt+1}/8)...")
        imap.select("INBOX")
        status, messages = imap.search(None, '(SINCE "%s" (FROM "noreply" OR SUBJECT "verify" OR SUBJECT "verification" OR SUBJECT "code"))' % time.strftime("%d-%b-%Y"))
        if status != "OK":
            log(f"⚠️ 搜索失败")
            time.sleep(8)
            continue

        msg_ids = messages[0].split()
        if not msg_ids:
            log("⚠️ 未找到验证码邮件")
            time.sleep(8)
            continue

        for msg_id in reversed(msg_ids):
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            codes = re.findall(r'\b[0-9]{6}\b', body)
            if codes:
                code = codes[0]
                log(f"✅ 找到验证码: {code}")
                imap.logout()
                return code

            codes = re.findall(r'\b[0-9]{4,8}\b', body)
            if codes:
                code = codes[0]
                log(f"✅ 找到验证码(变长): {code}")
                imap.logout()
                return code

        log("⚠️ 未找到6位验证码，等待...")
        time.sleep(8)

    imap.logout()
    log("❌ 超时未获取验证码")
    return None


def try_password_login(sb):
    """密码登录 (当前页面有 email+password 表单)"""
    log("🔐 尝试密码登录...")
    try:
        sb.type('input[id="email"], input[name="email"], input[type="email"], input[name="identifier"]', EMAIL, timeout=6)
        log("✅ 已填邮箱")
    except Exception as e:
        log(f"⚠️ 填邮箱: {e}")
        return False
    time.sleep(1)

    try:
        has_pwd = sb.is_element_present('input[id="password"], input[name="password"], input[type="password"]')
    except:
        has_pwd = False
    if not has_pwd:
        log("❌ 页面无密码框")
        return False

    try:
        sb.type('input[id="password"], input[name="password"], input[type="password"]', PASSWORD, timeout=6)
        log("✅ 已填密码")
    except Exception as e:
        log(f"⚠️ 填密码: {e}")
        return False
    time.sleep(1)

    handle_turnstile(sb)

    # 点登录按钮 (submit 或文字 Login)
    clicked = find_and_click(sb, ["login", "登录", "submit", "sign in"])
    if not clicked:
        try:
            sb.execute_script("""
                var f=document.querySelector('form');
                if(f){ f.requestSubmit ? f.requestSubmit() : f.submit(); }
            """)
            log("✅ form submit")
        except Exception as e:
            log(f"⚠️ form submit: {e}")
    time.sleep(10)

    u = get_url(sb)
    tx = innerText(sb).lower()
    log(f"📌 url={u}")
    if "login" in u.lower() or "auth" in u.lower():
        # 可能 Turnstile 未过, 再等一次
        time.sleep(10)
        u = get_url(sb)
    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 密码登录失败(仍在登录页)")
        shot(sb, "pwd_fail")
        return False
    log("✅ 密码登录成功")
    return True


def try_email_code_login(sb):
    """邮箱验证码登录兜底"""
    log("📧 尝试邮箱验证码登录...")
    try:
        sb.type('input[id="email"], input[name="email"], input[type="email"], input[name="identifier"]', EMAIL, timeout=6)
        log("✅ 已填邮箱")
    except Exception as e:
        log(f"⚠️ 填邮箱: {e}")
    time.sleep(1)

    # 点击 "Login with Email Code"
    if not find_and_click(sb, ["email code", "email code login", "验证码"]):
        log("⚠️ 未找到Email Code按钮")
    time.sleep(3)

    # 点击发送验证码
    if not find_and_click(sb, ["send", "request", "获取", "发送", "get code", "获取验证码"]):
        log("⚠️ 未找到发送按钮")

    if not GMAIL_APP_PASSWORD:
        log("❌ 未配置GMAIL_APP_PASSWORD")
        shot(sb, "no_app_pwd")
        return False

    code = get_verification_code()
    if not code:
        shot(sb, "no_code")
        return False

    # 填入验证码
    try:
        sb.type('input[name="code"], input[name="otp"], input[name="verification_code"], input[autocomplete="one-time-code"]', code, timeout=5)
        log(f"✅ 填入验证码: {code}")
    except:
        try:
            sb.execute_script(f"""
                var inputs=document.querySelectorAll('input');
                for(var i of inputs){{
                    if((i.type==='text'||i.type==='number'||i.type==='tel'||!i.type)&&!i.value){{
                        i.value='{code}';i.dispatchEvent(new Event('input',{{bubbles:true}}));break;
                    }}
                }}
            """)
            log(f"✅ JS填入验证码: {code}")
        except Exception as e:
            log(f"⚠️ 填入验证码: {e}")
    time.sleep(2)

    find_and_click(sb, ["verify", "确认", "login", "登录", "submit", "验证"])
    time.sleep(10)

    u = get_url(sb)
    tx = innerText(sb).lower()
    log(f"📌 {u} ({len(tx)}c)")
    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 验证码登录失败")
        shot(sb, "code_fail")
        return False
    log("✅ 验证码登录成功")
    return True


def find_renew_btn(sb):
    try:
        sel = 'button:contains("Renew Server"), a:contains("Renew Server")'
        if sb.is_element_visible(sel):
            log("✅ CSS 找到 Renew Server")
            return sb.find_element(sel)
    except:
        pass
    try:
        btn = sb.execute_script("""
            var els=document.querySelectorAll('button, a, div[role=button], span');
            for(var e of els){
                var t=(e.innerText||e.textContent||'').trim();
                if(t.toLowerCase().includes('renew')||t.toLowerCase().includes('extend')||t.includes('续期'))return e;
            }
            return null;
        """)
        if btn:
            log("✅ JS 找到续期按钮")
            return btn
    except:
        pass
    return None


def do_renew(sb):
    log(f"🌐 打开服务器页面 {SERVER_ID}...")
    if not nav(sb, DASHBOARD_URL, 25):
        return False
    time.sleep(6)

    # 关广告
    for i in range(3):
        time.sleep(2)
        try:
            for target in ['div:contains("Close")', 'span:contains("Close")', 'a:contains("Close")', 'button:contains("Hide")']:
                if sb.is_element_visible(target):
                    log("🧹 关广告")
                    sb.js_click(target)
                    time.sleep(2)
                    break
        except:
            pass

    # 滚到底部
    sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    if "google_vignette" in get_url(sb):
        log("⚠️ 跳转广告, 刷新...")
        sb.refresh()
        time.sleep(8)
        sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    shot(sb, "server_page")

    btn = find_renew_btn(sb)
    if not btn:
        log("❌ 未找到续期按钮")
        tx = innerText(sb)
        log(f"页面内容: {tx[:500]}")
        shot(sb, "no_btn")
        return False

    log("🖱️ 点击续期...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(1)
        sb.execute_script("arguments[0].click()", btn)
    except Exception as e:
        log(f"⚠️ 点击: {e}")
        try:
            sb.execute_script("arguments[0].click()", btn)
        except:
            pass
    time.sleep(8)

    handle_turnstile(sb)
    # 若有弹窗确认按钮
    find_and_click(sb, ["confirm", "确认", "yes", "renew", "续期"])
    time.sleep(20)
    shot(sb, "renew_done")

    tx = innerText(sb)
    log(f"📋 页面内容({len(tx)}c):")
    for line in tx.split("\n"):
        line = line.strip()
        if any(k in line.lower() for k in ["renewed", "renew", "expire", "expiry", "just", "last"]):
            log(f"  → {line}")

    log("🎉 续期流程完成")
    return True


def main():
    log("=" * 40)
    log("Zampto 续期 v8.0")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")
    log(f"📧 Gmail验证码: {'✅' if GMAIL_APP_PASSWORD else '❌ 未配置'}")

    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies={"http": PROXY, "https": PROXY}, timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理测试失败")

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            if not nav(sb, LOGIN_URL, 25):
                log("❌ 登录页打不开")
                send_tg("登录页打不开", "❌")
                return
            time.sleep(2)

            tx = innerText(sb)
            log(f"📄 登录页: {tx[:200]}")

            # 先试密码登录
            logged_in = try_password_login(sb)
            # 密码登录失败且页面有 Email Code 选项 → 邮箱验证码兜底
            if not logged_in:
                logged_in = try_email_code_login(sb)

            if not logged_in:
                log("❌ 登录失败")
                send_tg("登录失败: auth.zampto.net 宕机后 v8.0 已切回 dash.zampto.net, 请查看截图", "❌")
                return

            time.sleep(3)
            log("✅ 已登录")

            if do_renew(sb):
                log("🎉 续期完成")
                send_tg("续期完成", "✅")
            else:
                log("⚠️ 续期流程有问题")
                send_tg("续期流程有问题, 请查看截图", "⚠️")

    except Exception as e:
        import traceback
        log(f"💥 {e}")
        log(traceback.format_exc()[:500])
        send_tg(f"异常: {e}", "💥")


if __name__ == "__main__":
    main()