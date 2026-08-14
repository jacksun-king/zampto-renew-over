#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v7.0 (基于原版 akimify/Zampto-Renew)
登录入口: auth.zampto.net/sign-in (两步: 邮箱 → 密码)
"""
import os, time, json, requests
from seleniumbase import SB

# ===== 配置 =====
LOGIN_URL = "https://auth.zampto.net/sign-in?app_id=bmhk6c8qdqxphlyscztgl"
SERVER_ID = os.environ.get("SERVER_ID", "13420")
DASHBOARD_URL = f"https://dash.zampto.net/server?id={SERVER_ID}"
PROXY = os.environ.get("ALL_PROXY") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
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


# ===== 原版登录流程 =====
def login(sb):
    log("🔐 访问登录页...")
    sb.maximize_window()
    sb.uc_open_with_reconnect(LOGIN_URL, 4)
    time.sleep(3)

    # 等待登录框出现 (最多60s)
    log("⏳ 等待登录框...")
    login_ready = False
    for i in range(30):
        if sb.is_element_present('input[name="identifier"]'):
            log("✅ 登录框已就绪")
            login_ready = True
            break
        if sb.is_element_present('iframe') or sb.is_text_visible("Verify you are human") or sb.is_text_visible("security verification"):
            log(f"🔐 发现CF拦截 (第{i+1}次), 处理...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            try:
                cf_sel = 'iframe[title*="Cloudflare"], iframe[src*="challenge"], iframe[src*="turnstile"]'
                if sb.is_element_present(cf_sel):
                    sb.uc_click(cf_sel)
                else:
                    sb.uc_click('iframe')
            except:
                pass
            time.sleep(4)
        else:
            time.sleep(2)

    if not login_ready:
        shot(sb, "shield_fail")
        return False

    # 步骤1: 填邮箱
    log("📧 填邮箱...")
    sb.type('input[name="identifier"], input[type="email"], input[type="text"]', EMAIL)
    time.sleep(1)

    # 步骤2: 点Sign in
    log("🖱️ 点Sign in...")
    sb.click('button[type="submit"], button:contains("Sign in")')
    time.sleep(5)

    # 步骤3: 填密码
    log("🔑 填密码...")
    try:
        sb.wait_for_element_visible('input[type="password"]', timeout=15)
        sb.type('input[type="password"]', PASSWORD)
        time.sleep(1)
    except Exception as e:
        log(f"⚠️ 密码框: {e}")
        return False

    # 步骤4: 点Continue
    log("🖱️ 点Continue...")
    sb.click('button[type="submit"], button:contains("Continue")')
    time.sleep(12)

    # 步骤5: Turnstile
    log("🔐 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
    except Exception as e:
        log(f"⚠️ gui_click: {e}")
    time.sleep(2)
    try:
        cf_sel = 'iframe[title*="Cloudflare"], iframe[src*="challenge"], iframe[src*="turnstile"]'
        if sb.is_element_present(cf_sel):
            sb.uc_click(cf_sel)
        else:
            sb.uc_click('iframe')
    except Exception as e:
        log(f"⚠️ uc_click: {e}")
    time.sleep(25)

    u = sb.get_current_url()
    if "dash.zampto.net" in u or "auth.zampto.net" not in u:
        log("✅ 登录成功!")
        return True
    log("❌ 登录失败")
    shot(sb, "login_fail")
    return False


def find_renew_btn(sb):
    """查找续期按钮"""
    try:
        # 原版选择器
        sel = 'button:contains("Renew Server"), a:contains("Renew Server")'
        if sb.is_element_visible(sel):
            log("✅ CSS 找到 Renew Server")
            return sb.find_element(sel)
    except:
        pass

    # 回退: 遍历所有元素
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
    sb.uc_open_with_reconnect(DASHBOARD_URL, 3)
    time.sleep(8)

    # 关掉弹窗广告
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

    # 处理跳转广告
    if "google_vignette" in sb.get_current_url():
        log("⚠️ 跳转广告, 刷新...")
        sb.refresh()
        time.sleep(8)
        sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    shot(sb, "server_page")

    btn = find_renew_btn(sb)
    if not btn:
        log("❌ 未找到续期按钮")
        tx = sb.execute_script("return document.body.innerText||''")
        log(f"页面内容: {tx[:500]}")
        shot(sb, "no_btn")
        return False

    log("🖱️ 点击续期...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(1)
        sb.js_click(btn)
    except Exception as e:
        log(f"⚠️ 点击: {e}")
        try:
            sb.execute_script("arguments[0].click()", btn)
        except:
            pass
    time.sleep(8)

    # 处理弹窗Turnstile
    try:
        cf_sel = 'iframe[title*="Cloudflare"], iframe[src*="challenge"], iframe[src*="turnstile"]'
        if sb.is_element_present(cf_sel):
            sb.uc_gui_click_captcha()
            time.sleep(2)
            sb.uc_click(cf_sel)
    except Exception as e:
        log(f"⚠️ 弹窗CF: {e}")

    time.sleep(25)
    shot(sb, "renew_done")

    # 检查续期结果
    tx = sb.execute_script("return document.body.innerText||''")
    log(f"📋 页面内容({len(tx)}c):")
    for line in tx.split("\n"):
        line = line.strip()
        if any(k in line.lower() for k in ["renewed", "renew", "expire", "expiry", "just", "last"]):
            log(f"  → {line}")

    log("🎉 续期流程完成")
    return True


def main():
    log("=" * 40)
    log("Zampto 续期 v7.0")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")

    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies={"http": PROXY, "https": PROXY}, timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理测试失败")

    # 清理代理环境变量(浏览器不用)
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)

            if not login(sb):
                log("❌ 登录失败")
                send_tg("登录失败", "❌")
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