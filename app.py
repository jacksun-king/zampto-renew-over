#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
import base64
from seleniumbase import SB

# ===== 从环境变量获取配置 =====
EMAIL = os.environ.get("ZAMPTO_EMAIL") or ""
PASSWORD = os.environ.get("ZAMPTO_PASSWORD") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
SERVER_ID = os.environ.get("SERVER_ID") or "13421"

BASE_URL = "https://dash.zampto.net"

# ===== Telegram 推送 =====
def send_tg_message(status_icon, status_text, detail=""):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG，跳过推送")
        return
    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = EMAIL[:2] + '****'
    text = (
        f"🖥 Zampto 续期通知\n\n"
        f"{status_icon} {status_text}\n"
        f"👤 {masked_email}\n"
        f"⏱️ {current_time_str}"
    )
    if detail:
        text += f"\n📋 {detail}"
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
        if r.status_code == 200:
            print("📩 Telegram 通知发送成功！")
        else:
            print(f"⚠️ Telegram 通知发送失败: {r.text}")
    except Exception as e:
        print(f"⚠️ Telegram 通知异常: {e}")

def send_tg_photo(filepath, caption=""):
    """发送截图到 Telegram 用于调试"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        with open(filepath, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": TG_CHAT_ID, "caption": caption[:200]}
            r = requests.post(url, files=files, data=data, timeout=15)
            if r.status_code == 200:
                print("📸 截图已发送到 Telegram")
            else:
                print(f"⚠️ 截图发送失败: {r.text}")
    except Exception as e:
        print(f"⚠️ 截图发送异常: {e}")

# ===== Turnstile / 验证码处理 JS =====
_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px';
            f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible';
            f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    return document.querySelector('input[name="cf-turnstile-response"]') !== null;
})()
"""

_SOLVED_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

def js_fill_input(sb, selector, text):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, "value"
        ).set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)

def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--class", cls],
                capture_output=True, text=True, timeout=3
            )
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wids[0]],
                    timeout=3, stderr=subprocess.DEVNULL
                )
                time.sleep(0.2)
                return
        except Exception:
            pass

def handle_turnstile(sb) -> bool:
    print("🔍 处理 Cloudflare Turnstile 验证...")
    time.sleep(2)
    if sb.execute_script(_SOLVED_JS):
        print("✅ 已静默通过")
        return True
    for _ in range(3):
        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass
        time.sleep(0.5)
    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
            return True
        print(f"🖱️ 第 {attempt + 1} 次调用 uc_gui_click_captcha...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            print(f"⚠️ uc_gui_click_captcha 异常: {e}")
        for _ in range(16):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
                return True
        print(f"⚠️ 第 {attempt + 1} 次未通过，重试...")
    print(" ❌ Turnstile 6 次均失败")
    return False

def wait_for_login_form(sb, timeout=60):
    """等待登录表单加载"""
    print(f"⏳ 等待页面加载（最长 {timeout}s）...")
    for i in range(timeout):
        try:
            page_src = (sb.get_page_source() or "").lower()

            # 检查登录表单元素（zampto 使用 id="email" 而非 name="email"）
            if 'id="email"' in page_src or 'type="email"' in page_src:
                print(f"✅ 登录表单已加载（{i+1}s）")
                return True

            # 检查是否跳转到了其他页面
            cur_url = sb.get_current_url().split('?')[0].lower().rstrip('/')
            login_url_lower = f"{BASE_URL}/auth/login".lower().rstrip('/')
            if cur_url != login_url_lower and 'auth' not in cur_url:
                print(f"✅ 已跳转到其他页面: {cur_url}（{i+1}s）")
                return True

        except Exception:
            pass
        time.sleep(1)

    print("⚠️ 页面加载超时，尝试保存截图...")
    try:
        sb.save_screenshot("page_state.png")
        send_tg_photo("page_state.png", "页面加载超时：当前页面状态")
    except Exception:
        pass
    return False

def has_cf_challenge(sb):
    """检测当前页面是否是 Cloudflare 挑战页面"""
    try:
        title = sb.get_page_title() or ""
        # 只检查 title，不检查源码（源码中可能包含误匹配文本）
        if 'just a moment' in title.lower():
            return True
        return False
    except Exception:
        return False

# ===== 登录 =====
def login(sb) -> bool:
    login_url = f"{BASE_URL}/auth/login"
    print(f"🌐 打开登录页面: {login_url}")

    # 使用 uc_open_with_reconnect 处理 Cloudflare
    # reconnect_time 每次重连等待秒数，总耗时 reconnect_time * 尝试次数
    sb.uc_open_with_reconnect(login_url, reconnect_time=10)
    time.sleep(3)

    # 检查是否还在 Cloudflare 挑战页
    if has_cf_challenge(sb):
        print("⚠️ 检测到 Cloudflare 挑战页，等待处理...")
        for i in range(30):
            time.sleep(1)
            if not has_cf_challenge(sb):
                print(f"✅ Cloudflare 挑战已通过（{i+1}s）")
                break
            if i % 10 == 0:
                print(f"⏳ 等待 Cloudflare 通过...（{i+1}s）")

    # 等待登录表单加载
    if not wait_for_login_form(sb, timeout=60):
        # 尝试再次使用 uc_open_with_reconnect
        print("🔄 首次加载失败，再次尝试 uc_open_with_reconnect...")
        try:
            sb.uc_open_with_reconnect(login_url, reconnect_time=15)
            time.sleep(5)
            if wait_for_login_form(sb, timeout=45):
                print("✅ 第二次尝试成功")
            else:
                print("❌ 页面始终未加载出登录表单")
                try:
                    # 打印当前页面部分内容用于调试
                    body = sb.get_text('body')[:500]
                    print(f"📄 页面内容: {body}")
                except Exception:
                    pass
                return False
        except Exception as e:
            print(f"❌ 第二次打开页面失败: {e}")
            return False

    # 填写邮箱（zampto 使用 id="email" 而非 name="email"）
    print("📧 填写邮箱...")
    js_fill_input(sb, '#email', EMAIL)
    time.sleep(0.3)

    # 填写密码（zampto 使用 id="password" 而非 name="password"）
    print("🔑 填写密码...")
    js_fill_input(sb, '#password', PASSWORD)
    time.sleep(1)

    # 等待 Turnstile 出现
    print("⏳ 等待 Turnstile 验证框出现...")
    ts_found = False
    for i in range(10):
        if sb.execute_script(_EXISTS_JS):
            ts_found = True
            print(f"✅ 检测到 Turnstile（{i+1}s）")
            break
        time.sleep(1)
    if ts_found:
        if not handle_turnstile(sb):
            print("⚠️ Turnstile 验证未通过，尝试直接提交...")
    else:
        print("ℹ️ 未检测到 Turnstile")

    # 点击 Login 提交按钮
    print("🖱️ 点击 Login 按钮...")
    try:
        sb.click('button[type="submit"]')
    except Exception:
        try:
            sb.press_keys('#password', '\n')
        except Exception:
            pass

    # 等待登录跳转（最长 30 秒）
    print("⏳ 等待登录跳转最长 30 秒...")
    for _ in range(30):
        time.sleep(1)
        cur_url = sb.get_current_url().split('?')[0].lower().rstrip('/')
        if cur_url != login_url.rstrip('/') and 'auth' not in cur_url:
            break

    cur_url = sb.get_current_url().split('?')[0].lower().rstrip('/')
    print(f"📄 当前 URL: {sb.get_current_url()}")
    if 'auth' not in cur_url and 'login' not in cur_url:
        print(f"✅ 登录成功！")
        return True
    print(f"❌ 登录失败，页面未跳转。(URL: {sb.get_current_url()})")
    try:
        sb.save_screenshot("login_failed.png")
        send_tg_photo("login_failed.png", "登录失败页面截图")
    except Exception:
        pass
    return False

# ===== 续期流程 =====
def check_renewal_info(sb) -> str:
    """读取页面上的续期信息"""
    time.sleep(3)
    try:
        info_text = sb.get_text('body')
        lines = info_text.split('\n')
        renewal_lines = []
        for line in lines:
            l = line.strip()
            if any(kw in l.lower() for kw in ['renew', 'expir', 'last renew', 'next renew']):
                renewal_lines.append(l)
        if renewal_lines:
            return '\n'.join(renewal_lines)
        return ""
    except Exception:
        return ""

def renew_server(sb) -> bool:
    """登录成功后进入服务器页面并触发续期"""
    server_url = f"{BASE_URL}/server?id={SERVER_ID}"
    print(f"\n🌐 打开服务器页面: {server_url}")
    sb.uc_open_with_reconnect(server_url, reconnect_time=10)
    time.sleep(5)

    if not wait_for_login_form(sb, timeout=30):
        print("⚠️ 服务器页面加载异常，继续尝试...")

    # 查找 Renew Server 按钮
    print("🔍 查找 Renew Server 按钮...")
    renew_btn = None
    selectors = [
        'button:has(svg.lucide-refresh-cw)',
        'button:has-text("Renew")',
        'button:has-text("Renew Server")',
        'button[data-slot="button"]:has(svg)',
        'button.w-full.bg-gradient-to-r',
    ]
    for sel in selectors:
        try:
            renew_btn = sb.find_element(sel, timeout=5)
            print(f"✅ 通过选择器找到按钮: {sel}")
            break
        except Exception:
            continue

    if not renew_btn:
        try:
            buttons = sb.find_elements('button')
            for btn in buttons:
                txt = (btn.text or "").strip()
                if 'renew' in txt.lower():
                    renew_btn = btn
                    print(f"✅ 通过文本找到按钮: {txt}")
                    break
        except Exception:
            pass

    if not renew_btn:
        print("❌ 未找到 Renew Server 按钮")
        sb.save_screenshot("no_renew_btn.png")
        send_tg_photo("no_renew_btn.png", "未找到续期按钮")
        info = check_renewal_info(sb)
        if info:
            print(f"📋 页面续期信息:\n{info}")
            send_tg_message("ℹ️", "未到续期时间", info)
        return False

    # 滚动到按钮并点击
    print("🖱️ 点击 Renew Server 按钮...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", renew_btn)
        time.sleep(0.5)
        renew_btn.click()
        print("✅ 已点击 Renew 按钮")
    except Exception as e:
        print(f"⚠️ 点击失败: {e}")
        try:
            renew_btn.click()
        except Exception:
            return False

    time.sleep(3)

    # 处理续期后的 Turnstile 验证
    print("🔍 检查是否有 Turnstile 验证...")
    ts_found = False
    for i in range(10):
        if sb.execute_script(_EXISTS_JS):
            ts_found = True
            print(f"✅ 检测到续期 Turnstile（{i+1}s）")
            break
        time.sleep(1)
    if ts_found:
        if not handle_turnstile(sb):
            print("⚠️ 续期 Turnstile 验证未通过，继续尝试提交...")

    # 等待续期结果
    print("⏳ 等待续期结果...")
    time.sleep(5)

    # 读取续期信息
    info = check_renewal_info(sb)
    if info:
        print(f"📋 续期信息:\n{info}")
        info_lower = info.lower()
        if 'expir' in info_lower or 'renewed' in info_lower or 'renewal' in info_lower:
            import re
            expiry_match = re.search(r'Expiry[^:]*:\s*([^\n]+)', info)
            if expiry_match:
                expiry_text = expiry_match.group(1).strip()
                print(f"✅ 续期成功！到期时间: {expiry_text}")
                send_tg_message("✅", "续期成功", f"到期: {expiry_text}")
            else:
                send_tg_message("✅", "续期成功", info[:100])
            return True
        else:
            send_tg_message("ℹ️", "续期操作已执行", info[:100])
            return True
    else:
        time.sleep(3)
        info = check_renewal_info(sb)
        if info:
            print(f"📋 续期信息:\n{info}")
            send_tg_message("✅", "续期成功", info[:100])
            return True
        else:
            print("ℹ️ 未检测到续期信息，可能续期未生效")
            sb.save_screenshot("renew_result.png")
            send_tg_photo("renew_result.png", "续期结果截图")
            send_tg_message("⚠️", "续期结果未知", "请查看截图")
            return False

# ===== 主入口 =====
def main():
    print("#" * 25)
    print(" Zampto 自动登录续期")
    print("#" * 25)

    if not EMAIL or not PASSWORD:
        print("❌ 未配置 ZAMPTO_EMAIL 或 ZAMPTO_PASSWORD")
        return

    # zampto.net 的 Cloudflare 配置会封锁代理 IP，必须直连
    # 即使有 NODE_LINK 也不挂代理，避免 Cloudflare 挑战页
    print("🌐 直连访问（zampto.net 封锁代理 IP，必须直连）")

    print("🚀 启动浏览器...")
    with SB(uc=True, headless=False) as sb:
        if login(sb):
            renew_server(sb)
        else:
            print("\n❌ 登录失败，终止续期操作。")
            send_tg_message("❌", "登录失败", "请检查截图")

if __name__ == "__main__":
    main()