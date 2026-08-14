#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v6.1
修复: Gmail IMAP验证码登录 + CSS选择器兼容
"""
import os, time, json, re, imaplib, email
import requests
from seleniumbase import SB

EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
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


def find_btn(sb):
    for sel in ['button', 'a', 'div[role=button]', 'span', 'input[type=submit]']:
        try:
            for e in sb.find_elements(sel):
                t = (e.text or "").strip()
                if t and ("renew" in t.lower() or "extend" in t.lower() or "续期" in t):
                    log(f"✅ CSS: '{t}'")
                    return e
        except:
            continue
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


def find_and_click(sb, keywords):
    """JS查找包含关键字的按钮并点击"""
    kw_str = " || ".join([f"t.includes('{kw}')" for kw in keywords])
    result = sb.execute_script(f"""
        var btns=document.querySelectorAll('button, a, div[role=button], span, input[type=submit]');
        for(var b of btns){{
            var t=(b.innerText||b.textContent||b.value||'').trim().toLowerCase();
            if({kw_str}){{return b;}}
        }}
        return null;
    """)
    if result:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", result)
        time.sleep(0.5)
        sb.execute_script("arguments[0].click()", result)
        return True
    return False


def get_verification_code():
    """从Gmail读取最新的验证码"""
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

        # 搜索最近10分钟的邮件
        status, messages = imap.search(None, f'(SINCE "{time.strftime("%d-%b-%Y")}" (FROM "noreply" OR SUBJECT "verify" OR SUBJECT "verification" OR SUBJECT "code"))')
        if status != "OK":
            log(f"⚠️ 搜索失败: {messages}")
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


def main():
    log("=" * 40)
    log("Zampto 续期 v6.1")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")
    log(f"📧 Gmail验证码: {'✅' if GMAIL_APP_PASSWORD else '❌ 未配置'}")

    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies=proxy_dict(), timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理不可用")

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            if not nav(sb, BASE_URL, 25):
                log("❌ 首页打不开")
                send_tg("首页打不开", "❌")
                return
            time.sleep(2)

            # 导航到登录页
            if not nav(sb, f"{BASE_URL}/auth/login", 25):
                log("❌ 登录页打不开")
                return
            time.sleep(2)

            tx = innerText(sb)
            src = sb.get_page_source() or ""
            has_email_code = any(kw in tx.lower() for kw in ["email code", "verification", "验证码"])
            has_password = 'input[type="password"]' in src or 'name="password"' in src
            log(f"  页面: 邮箱验证码={'✅' if has_email_code else '❌'}, 密码表单={'✅' if has_password else '❌'}")

            if has_password and not has_email_code:
                # 密码登录
                log("🔐 密码登录...")
                try:
                    sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
                    sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
                    log("✅ 已填写")
                    time.sleep(1)
                except Exception as e:
                    log(f"⚠️ 填写失败: {e}")

                try:
                    sb.uc_gui_click_captcha()
                    time.sleep(4)
                    log("✅ Turnstile 已处理")
                except Exception as e:
                    log(f"⚠️ Turnstile: {e}")

                find_and_click(sb, ["login", "登录", "submit"])
                time.sleep(8)

                u = get_url(sb)
                if "login" in u.lower() or "auth" in u.lower():
                    log("❌ 密码登录失败")
                    shot(sb, "pwd_fail")
                    return False
                log("✅ 密码登录成功")
            elif has_email_code or not has_password:
                # 邮箱验证码登录
                log("📧 邮箱验证码登录...")

                # 确认邮箱已填
                try:
                    sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
                    log("✅ 已填邮箱")
                except Exception as e:
                    log(f"⚠️ 填邮箱: {e}")
                time.sleep(1)

                # 点击 Email Code 按钮
                if find_and_click(sb, ["email code", "email", "验证码", "verification"]):
                    log("✅ 已点击邮箱验证码")
                    time.sleep(2)
                else:
                    log("⚠️ 未找到Email Code按钮，继续...")

                # 点击发送验证码
                if find_and_click(sb, ["send", "request", "获取", "发送", "get code", "获取验证码"]):
                    log("✅ 已点击发送验证码")
                    time.sleep(2)
                else:
                    log("⚠️ 未找到发送按钮")

                if not GMAIL_APP_PASSWORD:
                    log("❌ 未配置GMAIL_APP_PASSWORD")
                    shot(sb, "no_app_pwd")
                    send_tg("登录失败：未配置Gmail应用密码", "❌")
                    return

                code = get_verification_code()
                if not code:
                    shot(sb, "no_code")
                    return

                # 填入验证码
                try:
                    sb.type('input[name="code"], input[name="otp"], input[name="verification_code"]', code, timeout=5)
                    log(f"✅ 填入验证码: {code}")
                except:
                    try:
                        sb.execute_script(f"""
                            var inputs=document.querySelectorAll('input');
                            for(var i of inputs){{
                                if((i.type==='text'||i.type==='number'||!i.type)&&!i.value){{
                                    i.value='{code}';i.dispatchEvent(new Event('input',{{bubbles:true}}));break;
                                }}
                            }}
                        """)
                        log(f"✅ JS填入验证码: {code}")
                    except Exception as e:
                        log(f"⚠️ 填入验证码: {e}")
                time.sleep(2)

                # 提交
                find_and_click(sb, ["verify", "确认", "login", "登录", "submit", "验证"])
                time.sleep(8)

                u = get_url(sb)
                tx = innerText(sb).lower()
                log(f"📌 {u} ({len(tx)}c)")
                if any(k in tx for k in ["dashboard", "服务器", "server", "expire", "renew"]):
                    log("✅ 验证码登录成功")
                elif "login" in u.lower() or "auth" in u.lower():
                    log("❌ 仍在登录页")
                    shot(sb, "code_fail")
                    return
                else:
                    log("✅ 登录成功")

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
            log(f"📄 {tx[:400]}")

            btn = find_btn(sb)
            if not btn:
                log("❌ 未找到续期按钮")
                shot(sb, "no_btn")
                send_tg("找不到续期按钮", "❌")
                return

            log("🖱️ 点击续期...")
            try:
                sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(1)
                sb.execute_script("arguments[0].click()", btn)
                log("✅ 点击成功")
            except Exception as e:
                log(f"⚠️ JS点击: {e}")
            time.sleep(5)

            shot(sb, "clicked")
            tl = innerText(sb).lower()

            if "security verification" in tl or "verify you are human" in tl:
                log("🔐 处理弹窗...")
                try:
                    sb.uc_gui_click_captcha()
                    time.sleep(5)
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