#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v8.1
修复(2026-08-17):
  1. 登录入口: auth.zampto.net/sign-in 已宕机(HTTP 522), 切回 dash.zampto.net/auth/login
  2. execute_script 顶层 return 报 Illegal return statement, 全部改 IIFE 写法
  3. Turnstile: 完整处理(cf-turnstile-response 填充检查 + uc_gui_click_captcha 循环)
  4. 续期: XPath 定位 'Renew Server' 按钮 + 剩余时间对比确认成功
"""
import os, time, json, re, imaplib, email, subprocess
import requests
from seleniumbase import SB

# ===== 配置 =====
LOGIN_URL = "https://dash.zampto.net/auth/login"
BASE_URL = "https://dash.zampto.net"
EMAIL_SELECTOR = "#email"
PASSWORD_SELECTOR = "#password"
SERVER_ID = os.environ.get("SERVER_ID", "13420")
DETAIL_URL = f"{BASE_URL}/server?id={SERVER_ID}"
PROXY = os.environ.get("ALL_PROXY") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

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
    try:
        sb.save_screenshot(f"{t}.png")
        log(f"📸{t}")
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


# ============================================================
# Turnstile 处理 (来自 myzampto 验证过的方案)
# ============================================================
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
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
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


def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls],
                               capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]],
                               timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"],
                       timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)],
                       timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")


def handle_turnstile(sb, max_attempts=3, timeout_per_attempt=20) -> bool:
    log(f"🔍 Turnstile 处理 (最多{max_attempts}次, 每次{timeout_per_attempt}s)...")
    time.sleep(2)

    try:
        if sb.execute_script(_SOLVED_JS):
            log("✅ Turnstile 已静默通过")
            return True
    except Exception:
        pass

    for _ in range(3):
        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass
        time.sleep(0.5)

    for attempt in range(max_attempts):
        attempt_start = time.time()
        try:
            if sb.execute_script(_SOLVED_JS):
                log("✅ Turnstile 通过(尝试前)")
                return True
        except Exception:
            pass

        log(f"🖱️ 第{attempt+1}次 uc_gui_click_captcha...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            log(f"⚠️ uc_gui_click_captcha: {e}")

        wait_count = 0
        while wait_count < timeout_per_attempt * 2:
            time.sleep(0.5)
            wait_count += 1
            try:
                if sb.execute_script(_SOLVED_JS):
                    elapsed = time.time() - attempt_start
                    log(f"✅ Turnstile 通过({elapsed:.1f}s)")
                    return True
            except Exception:
                pass
            if time.time() - attempt_start > timeout_per_attempt:
                break

    log("❌ Turnstile 多次失败")
    return False


# ============================================================
# 剩余时间提取
# ============================================================
def extract_remaining_minutes(sb):
    """从 'Expiry (Next Renewal)' 区域提取剩余时间(分钟)"""
    try:
        page_text = sb.execute_script("return document.body ? document.body.innerText : ''") or ""
    except Exception:
        page_text = ""
    match = re.search(
        r'Expiry\s*\(Next Renewal\).*?(?:(\d+)\s*d\s*)?(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?',
        page_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    return days * 1440 + hours * 60 + minutes


# ============================================================
# 登录
# ============================================================
def login(sb) -> bool:
    log(f"🌐 打开登录页: {LOGIN_URL}")
    try:
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=8)
    except Exception as exc:
        log(f"⚠️ 打开登录页失败: {exc}")
        return False

    log("⏳ 等待登录表单...")
    try:
        sb.wait_for_element(EMAIL_SELECTOR, timeout=30)
        sb.wait_for_element(PASSWORD_SELECTOR, timeout=30)
        log("✅ 登录表单加载成功")
    except Exception as exc:
        log(f"❌ 登录表单未加载: {exc}")
        log(f"当前 URL: {sb.get_current_url()}")
        sb.save_screenshot("login_form_fail.png")
        return False

    # Cookie 同意
    try:
        for button in sb.find_elements("button"):
            text = (button.text or "").strip().lower()
            if text in {"accept", "accept all", "同意", "接受"}:
                button.click()
                time.sleep(1)
                break
    except Exception:
        pass

    log(f"📧 填邮箱...")
    sb.update_text(EMAIL_SELECTOR, EMAIL)
    log(f"🔑 填密码...")
    sb.update_text(PASSWORD_SELECTOR, PASSWORD)
    time.sleep(1)

    # Turnstile
    try:
        has_ts = sb.execute_script(_EXISTS_JS)
    except Exception:
        has_ts = False
    if has_ts:
        log("🛡️ 检测到 Turnstile, 开始处理...")
        if not handle_turnstile(sb, max_attempts=3, timeout_per_attempt=20):
            log("❌ Turnstile 失败")
            sb.save_screenshot("login_turnstile_fail.png")
            return False
    else:
        log("ℹ️ 未检测到 Turnstile")

    # 提交登录
    log("🖱️ 提交登录...")
    submitted = False
    try:
        for btn in sb.find_elements("button"):
            text = (btn.text or "").strip().lower()
            if text in {"sign in", "log in", "login", "登录", "continue", "submit", "进入", "登 录", "sign in →"}:
                btn.click()
                submitted = True
                log(f"✅ 已点击: '{text}'")
                break
    except Exception as exc:
        log(f"⚠️ 点按钮: {exc}")

    if not submitted:
        try:
            sb.click(PASSWORD_SELECTOR)
            time.sleep(0.5)
            sb.press_keys(PASSWORD_SELECTOR, '\n')
            log("✅ 回车提交")
        except Exception as exc:
            log(f"⚠️ 回车提交: {exc}")
            return False

    log("⏳ 等待登录结果...")
    login_paths = {"/auth/login", "/login"}
    for i in range(30):
        time.sleep(1)
        try:
            current_url = sb.get_current_url()
            from urllib.parse import urlparse
            normalized = urlparse(current_url).path.rstrip("/").lower()
        except Exception:
            normalized = ""
        # 错误检测
        try:
            body_text = (sb.execute_script("return document.body ? document.body.innerText : ''") or "").lower()
            for kw in ("invalid email or password", "invalid credentials", "email or password is incorrect", "wrong password", "account not found"):
                if kw in body_text:
                    log(f"❌ 账号或密码错误: {kw}")
                    sb.save_screenshot("login_failed.png")
                    return False
        except Exception:
            pass

        if normalized not in login_paths:
            log("✅ 登录成功!")
            return True

        # 登录表单消失也判成功
        try:
            if not sb.is_element_present(EMAIL_SELECTOR) and not sb.is_element_present(PASSWORD_SELECTOR):
                log("✅ 表单已消失, 登录成功")
                return True
        except Exception:
            pass

        if (i + 1) % 5 == 0:
            log(f"   [诊断 {i+1}s] URL={current_url}")

    log("❌ 登录超时")
    sb.save_screenshot("login_timeout.png")
    return False


# ============================================================
# 续期
# ============================================================
def do_renew(sb) -> dict:
    result = {"status": "unknown", "detail": ""}
    log(f"🌐 打开详情页: {DETAIL_URL}")
    try:
        sb.get(DETAIL_URL)
        sb.wait_for_text("Server last renewed", timeout=10)
    except Exception:
        try:
            sb.wait_for_text("Expiry (Next Renewal)", timeout=10)
        except Exception:
            log("⚠️ 未检测到预期文字, 继续尝试...")
    time.sleep(3)

    # 关广告弹窗
    try:
        for button in sb.find_elements("button"):
            text = (button.text or "").strip().lower()
            if text in {"close", "hide", "×", "x", "关闭"} and len(text) <= 5:
                button.click()
                time.sleep(1)
                break
    except Exception:
        pass

    old_minutes = extract_remaining_minutes(sb)
    if old_minutes is not None:
        log(f"📅 原剩余: {old_minutes//1440}d {(old_minutes%1440)//60}h {old_minutes%60}m")
    else:
        log("⚠️ 未能提取原剩余时间")

    # 点击 Renew Server
    log("🖱️ 点击 Renew Server...")
    click_script = """
    (function() {
        var xpath = "//div[@data-slot='card'][.//div[contains(text(),'Server last renewed')]]//button[normalize-space()='Renew Server']";
        var button = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if (button) {
            button.scrollIntoView({behavior: 'smooth', block: 'center'});
            button.click();
            return 'success';
        }
        var buttons = document.querySelectorAll('button');
        for (var i = 0; i < buttons.length; i++) {
            if (buttons[i].textContent.trim() === 'Renew Server') {
                buttons[i].scrollIntoView({behavior: 'smooth', block: 'center'});
                buttons[i].click();
                return 'success';
            }
        }
        return 'not_found';
    })();
    """
    click_success = False
    try:
        time.sleep(1)
        msg = sb.execute_script(click_script)
        if msg == 'success':
            log("✅ 点击成功")
            click_success = True
    except Exception as e:
        log(f"⚠️ 点击失败: {e}")

    if not click_success:
        result["status"] = "error"
        result["detail"] = "找不到续期按钮"
        log("❌ 找不到续期按钮")
        sb.save_screenshot("click_failed.png")
        return result

    # 等待并检查时间变化
    time.sleep(5)
    early_success = False
    quick_check = extract_remaining_minutes(sb)
    if old_minutes is not None and quick_check is not None:
        time_change = quick_check - old_minutes
        if time_change > 0:
            result["status"] = "success"
            result["detail"] = f"续期成功! {old_minutes//1440}d→{quick_check//1440}d"
            log(f"✅ 提前确认续期成功(+{time_change}分钟)")
            early_success = True
        elif old_minutes == 0 and quick_check > 0:
            result["status"] = "success"
            result["detail"] = f"从过期恢复: {quick_check//1440}d"
            log("✅ 从过期恢复")
            early_success = True

    if not early_success:
        # Turnstile
        try:
            has_ts = sb.execute_script(_EXISTS_JS)
        except Exception:
            has_ts = False
        if has_ts:
            log("🛡️ 续期弹窗 Turnstile...")
            handle_turnstile(sb, max_attempts=3, timeout_per_attempt=20)
        else:
            log("ℹ️ 无续期 Turnstile")

        # 重新加载详情页
        log("⏳ 重新加载详情页...")
        time.sleep(3)
        try:
            sb.get(DETAIL_URL)
            sb.wait_for_text("Server last renewed", timeout=15)
            time.sleep(3)
        except Exception as e:
            log(f"⚠️ 重开详情页: {e}")

        new_minutes = extract_remaining_minutes(sb)
        if old_minutes is not None and new_minutes is not None:
            time_change = new_minutes - old_minutes
            if time_change > 0:
                result["status"] = "success"
                result["detail"] = f"续期成功! {old_minutes//1440}d→{new_minutes//1440}d (+{time_change}m)"
                log(f"✅ 续期成功(+{time_change}分钟)")
            elif old_minutes == 0 and new_minutes > 0:
                result["status"] = "success"
                result["detail"] = f"从过期恢复: {new_minutes//1440}d"
                log("✅ 从过期恢复")
            elif time_change == 0:
                result["status"] = "skipped"
                result["detail"] = "剩余时间未变化, 可能已续期/冷却"
                log("⏭️ 时间未变化(可能冷却中)")
            else:
                result["status"] = "unknown"
                result["detail"] = f"时间减少异常({time_change}m)"
                log(f"⚠️ 时间减少异常: {time_change}m")
        else:
            result["status"] = "unknown"
            result["detail"] = f"无法提取时间(原:{old_minutes}, 新:{new_minutes})"
            log("⚠️ 无法提取时间")

    sb.save_screenshot("result.png")
    return result


# ============================================================
# 主流程
# ============================================================
def main():
    log("=" * 40)
    log("Zampto 续期 v8.1")
    log("=" * 40)
    log(f"📌 服务器: {SERVER_ID}")

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

            if not login(sb):
                log("❌ 登录失败")
                send_tg("登录失败(检查截图)", "❌")
                return

            time.sleep(3)
            log("✅ 已登录")

            r = do_renew(sb)
            log(f"📋 结果: {r['status']} - {r['detail']}")
            if r["status"] == "success":
                send_tg(r["detail"], "✅")
            elif r["status"] == "skipped":
                send_tg(r["detail"], "⏭️")
            else:
                send_tg(f"{r['status']}: {r['detail']}", "⚠️")

    except Exception as e:
        import traceback
        log(f"💥 {e}")
        log(traceback.format_exc()[:500])
        send_tg(f"异常: {e}", "💥")


if __name__ == "__main__":
    main()