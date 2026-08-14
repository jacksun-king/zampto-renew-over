#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - 修复版 v2
关键修复: 不通过 ALL_PROXY 环境变量传代理，改用 SB proxy_string 参数
"""
import os, re, time, json, sys
import requests
from seleniumbase import SB

EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("SERVER_ID", "13421")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or ""
BASE_URL = "https://dash.zampto.net"

_shot_no = 0

def log(msg, notify=False):
    ts = time.strftime("%H:%M:%S", time.gmtime(time.time() + 8*3600))
    print(f"[{ts}] {msg}", flush=True)

def shot(sb, tag):
    global _shot_no
    _shot_no += 1
    try:
        sb.save_screenshot(f"{_shot_no:02d}_{tag}.png")
        log(f"📸 {_shot_no:02d}_{tag}")
    except: pass

def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID): return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} Zampto 续期\n\n{msg}"},
            timeout=15,
        )
    except: pass

def get_page_text(sb, selector="body", timeout=5):
    """安全获取页面文本"""
    try:
        return (sb.get_text(selector) or "")
    except: return ""

def get_cur_url(sb):
    """安全获取当前 URL"""
    try:
        return sb.get_current_url()
    except: return ""

def get_page_source(sb):
    """安全获取页面源码"""
    try:
        return sb.get_page_source()
    except: return ""

def wait_for_real_page(sb, timeout=25):
    """等待页面真正加载，不是 chrome://new-tab-page"""
    start = time.time()
    while time.time() - start < timeout:
        cur_url = get_cur_url(sb)
        body_text = get_page_text(sb)
        
        if not cur_url or "chrome://" in cur_url or "new-tab" in cur_url:
            time.sleep(2)
            continue
        if len(body_text) > 100 and "dash.zampto.net" in cur_url:
            log(f"✅ 页面加载完成: {cur_url} ({len(body_text)} chars)")
            return True
        time.sleep(1)
    return False

def navigate(sb, url, timeout=25):
    """可靠导航"""
    log(f"🌐 导航: {url}")
    for attempt in range(3):
        try:
            sb.open(url)
        except Exception as e:
            log(f"⚠️ 导航异常: {e}")
            time.sleep(3)
            continue
        
        if wait_for_real_page(sb, timeout=timeout):
            return True
        
        cur_url = get_cur_url(sb)
        log(f"⚠️ 页面加载失败 (尝试 {attempt+1}), URL: {cur_url}")
        shot(sb, f"nav_fail_{attempt}")
        time.sleep(5)
    
    return False

def check_page_valid(sb):
    """检查页面是否有效"""
    cur_url = get_cur_url(sb)
    body = get_page_text(sb).lower()
    
    if "chrome://" in cur_url or "new-tab" in cur_url:
        return False
    if len(body) < 50:
        return False
    if "just a moment" in body or "checking your browser" in body:
        log("⚠️ Cloudflare 挑战中...")
        time.sleep(10)
        return check_page_valid(sb)
    if "1005" in body:
        log("❌ Cloudflare 1005")
        return False
    return True

def login(sb):
    """登录 Zampto"""
    if not (EMAIL and PASSWORD):
        log("❌ 未配置邮箱密码")
        return False
    
    log("🌐 打开登录页...")
    if not navigate(sb, f"{BASE_URL}/auth/login", timeout=25):
        log("❌ 登录页打不开")
        return False
    
    shot(sb, "login_page")
    time.sleep(3)
    
    # 找登录表单
    try:
        sb.find_element('input[name="email"], input[type="email"]', timeout=10)
        log("✅ 登录表单就绪")
    except:
        log("⚠️ 未找到登录表单")
        body = get_page_text(sb)
        log(f"页面内容(前200): {body[:200]}")
        shot(sb, "no_login_form")
        return False
    
    # 输入
    try:
        sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
        log("✅ 输入邮箱")
        sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
        log("✅ 输入密码")
    except Exception as e:
        log(f"⚠️ 输入失败: {e}")
        return False
    
    time.sleep(2)
    
    # Turnstile
    try:
        sb.uc_gui_click_captcha(timeout=10)
        log("✅ Turnstile")
        time.sleep(3)
    except:
        log("⚠️ Turnstile 跳过")
    
    # 提交
    try:
        sb.click('button[type="submit"]', timeout=5)
    except:
        try:
            sb.execute_script("document.querySelector('form')?.submit()")
        except: pass
    
    time.sleep(5)
    
    cur_url = get_cur_url(sb)
    log(f"📌 登录后: {cur_url}")
    if "login" in cur_url.lower() or "auth" in cur_url.lower():
        log("❌ 登录失败")
        shot(sb, "login_failed")
        return False
    log("✅ 登录成功")
    return True

def do_renew(sb):
    """点击续期"""
    server_url = f"{BASE_URL}/server?id={SERVER_ID}"
    log(f"🌐 打开服务器页: {server_url}")
    
    if not navigate(sb, server_url, timeout=25):
        log("❌ 服务器页打不开")
        return False
    
    shot(sb, "server_page")
    time.sleep(3)
    
    if not check_page_valid(sb):
        log("❌ 页面无效")
        return False
    
    # 记录当前状态
    body = get_page_text(sb)
    title = ""
    try:
        title = sb.get_page_title() or ""
    except: pass
    log(f"📄 标题: {title}")
    log(f"📄 页面内容(前300): {body[:300]}")
    
    # 找续期按钮
    log("🔍 找续期按钮...")
    renew_btn = None
    for sel in ['button:contains("Renew")', 'button:contains("Extend")', 'button:contains("续期")']:
        try:
            elems = sb.find_elements(sel)
            if elems:
                renew_btn = elems[0]
                log(f"  ✅ 按钮: '{(renew_btn.text or '').strip()}'")
                break
        except: continue
    
    if not renew_btn:
        try:
            for btn in sb.find_elements("button"):
                txt = (btn.text or "").strip()
                if txt and ("renew" in txt.lower() or "extend" in txt.lower() or "续期" in txt):
                    renew_btn = btn
                    log(f"  ✅ 遍历: '{txt}'")
                    break
        except: pass
    
    if not renew_btn:
        log("❌ 未找到续期按钮")
        shot(sb, "no_btn")
        body = get_page_text(sb)
        log(f"页面内容: {body[:500]}")
        return False
    
    # 点击
    log("🖱️ 点击...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", renew_btn)
        time.sleep(1)
        sb.execute_script("arguments[0].click()", renew_btn)
        log("✅ 点击成功")
    except Exception as e:
        log(f"⚠️ 点击: {e}")
        try:
            renew_btn.click()
        except: pass
    
    time.sleep(5)
    shot(sb, "clicked")
    
    # 处理 Turnstile 弹窗
    body_lower = get_page_text(sb).lower()
    if "security verification" in body_lower or "complete the security" in body_lower:
        log("🔐 Turnstile 弹窗...")
        try:
            sb.uc_gui_click_captcha(timeout=10)
            time.sleep(5)
        except: pass
        time.sleep(3)
    
    # 检查结果
    body = get_page_text(sb)
    for line in body.split("\n"):
        l = line.strip()
        if "last renewed" in l.lower() or "just renewed" in l.lower() or "renewed" in l.lower():
            log(f"📋 {l}")
    
    shot(sb, "result")
    return True

def main():
    log("=" * 40)
    log("Zampto 自动续期 v2")
    log("=" * 40)
    log(f"📌 代理: {PROXY or '直连'}")
    log(f"📌 服务器: {SERVER_ID}")
    
    # 测试代理
    if PROXY:
        try:
            r = requests.get("https://api.ipify.org", proxies={"http": PROXY, "https": PROXY}, timeout=10)
            log(f"🌐 出口 IP: {r.text.strip()}")
        except:
            log("⚠️ 代理测试失败")
    
    # 构建 SB 参数
    sb_kwargs = {"uc": True, "headless2": True, "incognito": False}
    if PROXY:
        # 用 proxy_string 而不是环境变量
        proxy_str = PROXY.replace("http://", "").replace("https://", "")
        if ":" in proxy_str:
            host, port = proxy_str.split(":", 1)
            sb_kwargs["proxy_string"] = f"{host}:{port}"
        log(f"📌 Chrome 代理: {proxy_str}")
    
    # 不要设置 ALL_PROXY 环境变量给 Chrome
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("HTTP_PROXY", None)
    
    try:
        log("🚀 启动浏览器...")
        with SB(**sb_kwargs) as sb:
            log("✅ 浏览器就绪")
            time.sleep(2)
            
            # 打开首页
            if not navigate(sb, BASE_URL, timeout=25):
                log("❌ 首页打不开")
                send_tg("首页打不开", "❌")
                return
            
            time.sleep(3)
            
            # 检查登录状态
            cur_url = get_cur_url(sb)
            body_lower = get_page_text(sb).lower()
            if ("login" in cur_url.lower() or "auth" in cur_url.lower()) and "server" not in body_lower:
                log("🔐 需登录")
                if not login(sb):
                    send_tg("登录失败", "❌")
                    return
            else:
                log("✅ 已登录")
            
            # 续期
            log("=" * 40)
            ok = do_renew(sb)
            if ok:
                log("🎉 续期操作完成")
                send_tg("续期操作已执行", "✅")
            else:
                log("❌ 续期失败")
                send_tg("续期失败", "❌")
    except Exception as e:
        log(f"💥 异常: {e}")
        send_tg(f"异常: {e}", "💥")

if __name__ == "__main__":
    main()