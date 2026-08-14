#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v6.0
新增: 邮箱验证码自动登录 (Gmail IMAP + App Password)
"""
import os, time, json, re, imaplib, email
from email.header import decode_header
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

    for attempt in range(5):
        log(f"📧 搜索验证码邮件 (尝试 {attempt+1}/5)...")
        imap.select("INBOX")
        # 搜索最近5分钟的邮件
        status, messages = imap.search(None, f'(SINCE "{time.strftime("%d-%b-%Y")}" (SUBJECT "verify" OR SUBJECT "verification" OR SUBJECT "Zampto" OR SUBJECT "code"))')
        if status != "OK":
            log(f"⚠️ 搜索失败: {messages}")
            time.sleep(8)
            continue

        msg_ids = messages[0].split()
        if not msg_ids:
            log("⚠️ 未找到验证码邮件")
            time.sleep(8)
            continue

        # 取最新的邮件
        for msg_id in reversed(msg_ids):
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # 获取正文
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            # 提取6位验证码
            codes = re.findall(r'\b[0-9]{6}\b', body)
            if codes:
                code = codes[0]
                log(f"✅ 找到验证码: {code}")
                imap.logout()
                return code

            # 没有6位数字，尝试4位或更多格式
            codes = re.findall(r'\b[0-9]{4,8}\b', body)
            if codes:
                code = codes[0]
                log(f"✅ 找到验证码(变长): {code}")
                imap.logout()
                return code

        log("⚠️ 邮件中找到但无验证码数字，等待新邮件...")
        time.sleep(8)

    imap.logout()
    log("❌ 超时未获取验证码")
    return None


def email_code_login(sb):
    """邮箱验证码登录流程"""
    log("📧 邮箱验证码登录流程...")
    if not nav(sb, f"{BASE_URL}/auth/login", 25):
        return False
    time.sleep(3)

    # 检查页面上是否有邮箱验证码选项
    try:
        src = sb.get_page_source() or ""
        has_email_code = "email code" in src.lower() or "email code" in innerText(sb).lower()
        has_password = 'input[type="password"]' in src or 'name="password"' in src
        log(f"  页面: 邮箱验证码={'✅' if has_email_code else '❌'}, 密码表单={'✅' if has_password else '❌'}")
    except:
        has_email_code = False
        has_password = False

    if has_password:
        # 如果还有密码表单，试试密码登录
        return try_password_login(sb)

    # 密码表单不存在，用邮箱验证码
    # Step 1: 点击 "Login with Email Code" 或类似按钮
    try:
        sb.click('button:contains("Email Code"), a:contains("Email Code"), button:contains("邮箱"), button:contains("verification code")', timeout=8)
        log("✅ 已点击邮箱验证码")
        time.sleep(3)
    except Exception as e:
        log(f"⚠️ 点击邮箱验证码: {e}")
        # 尝试通用按钮
        try:
            sb.execute_script("""
                var btns=document.querySelectorAll('button, a');
                for(var b of btns){
                    var t=(b.innerText||b.textContent||'').trim().toLowerCase();
                    if(t.includes('email')||t.includes('code')||t.includes('verification')){b.click();break;}
                }
            """)
            log("✅ JS点击邮箱验证码")
            time.sleep(3)
        except Exception as e2:
            log(f"⚠️ JS也失败: {e2}")

    # Step 2: 确认邮箱已填入，如果没有则填入
    try:
        email_input = sb.find_element('input[name="email"], input[type="email"]')
        current_email = sb.execute_script("return arguments[0].value;", email_input)
        if not current_email or current_email != EMAIL:
            sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
            log(f"✅ 填入邮箱: {EMAIL}")
    except:
        log("⚠️ 邮箱输入框查找失败")

    # Step 3: 点击发送验证码
    try:
        sb.click('button:contains("Send"), button:contains("Request"), button:contains("获取"), button:contains("发送"), button:contains("Get Code")', timeout=8)
        log("✅ 已点击发送验证码")
        time.sleep(3)
    except Exception as e:
        log(f"⚠️ 点击发送: {e}")
        try:
            sb.execute_script("""
                var btns=document.querySelectorAll('button, a');
                for(var b of btns){
                    var t=(b.innerText||b.textContent||'').trim().toLowerCase();
                    if(t.includes('send')||t.includes('request')||t.includes('get')||t.includes('code')){b.click();break;}
                }
            """)
            log("✅ JS点击发送")
            time.sleep(3)
        except:
            pass

    # Step 4: 从Gmail获取验证码
    if not GMAIL_APP_PASSWORD:
        log("❌ 未配置GMAIL_APP_PASSWORD，无法自动获取验证码")
        return False

    code = get_verification_code()
    if not code:
        return False

    # Step 5: 填入验证码
    try:
        sb.type('input[name="code"], input[name="otp"], input[name="verification_code"], input[type="text"]', code, timeout=5)
        log(f"✅ 填入验证码: {code}")
        time.sleep(2)
    except Exception as e:
        log(f"⚠️ 填入验证码: {e}")
        try:
            # 找到6位数字输入框
            sb.execute_script(f"""
                var inputs=document.querySelectorAll('input');
                for(var i of inputs){{
                    if(i.type==='text'||i.type==='number'||!i.type){{
                        if(!i.value)i.value='{code}';
                    }}
                }}
            """)
            log("✅ JS填入验证码")
        except:
            pass

    # Step 6: 提交
    try:
        sb.click('button[type="submit"], button:contains("Verify"), button:contains("确认"), button:contains("Login")', timeout=8)
        log("✅ 已点击验证/登录")
    except Exception as e:
        log(f"⚠️ 点击验证: {e}")
        try:
            sb.execute_script("document.querySelector('form')?.submit()")
        except:
            pass

    time.sleep(8)
    u = get_url(sb)
    tx = innerText(sb).lower()
    log(f"📌 {u} ({len(tx)}c)")

    if any(k in tx for k in ["dashboard", "服务器", "server", "expire", "renew"]):
        log("✅ 验证码登录成功")
        return True
    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 仍在登录页")
        shot(sb, "email_code_fail")
        return False
    log("✅ 登录成功")
    return True


def try_password_login(sb):
    """密码登录(旧方式，备用)"""
    log("🔐 尝试密码登录...")
    try:
        sb.wait_for_element('input[name="email"], input[type="email"]', timeout=5)
    except:
        return False

    try:
        sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
        sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
        log("✅ 已填写密码")
        time.sleep(1)
    except Exception as e:
        log(f"⚠️ 填写失败: {e}")
        return False

    # Turnstile
    try:
        sb.uc_gui_click_captcha()
        time.sleep(4)
    except Exception as e:
        log(f"⚠️ Turnstile: {e}")

    try:
        sb.click('button[type="submit"]', timeout=5)
        log("✅ 已提交")
    except:
        pass
    time.sleep(8)

    u = get_url(sb)
    if "login" in u.lower() or "auth" in u.lower():
        log("❌ 密码登录失败")
        return False
    log("✅ 密码登录成功")
    return True


def main():
    log("=" * 40)
    log("Zampto 续期 v6.0")
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

    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            if not nav(sb, BASE_URL, 25):
                log("❌ 首页打不开")
                send_tg("首页打不开", "❌")
                return
            time.sleep(2)

            # 尝试邮箱验证码登录
            if not email_code_login(sb):
                log("❌ 登录失败")
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