#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - 精简版
不通过系统代理环境变量，Chrome 直连（UC 模式自带反检测）
"""
import os, time, json
import requests
from seleniumbase import SB

EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("SERVER_ID", "13421")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or ""
BASE_URL = "https://dash.zampto.net"

_shot = 0
def log(m):
    ts = time.strftime("%H:%M:%S", time.gmtime(time.time()+28800))
    print(f"[{ts}] {m}", flush=True)

def shot(sb, t):
    global _shot; _shot+=1
    try: sb.save_screenshot(f"{_shot:02d}_{t}.png"); log(f"📸 {_shot:02d}_{t}")
    except: pass

def send_tg(m, i="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID): return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{i} Zampto\n\n{m}"}, timeout=15)
    except: pass

def txt(sb, s="body"):
    try: return (sb.get_text(s) or "")
    except: return ""

def url(sb):
    try: return sb.get_current_url()
    except: return ""

def wait_page(sb, t=20):
    st=time.time()
    while time.time()-st<t:
        u=url(sb); tx=txt(sb)
        if u and "dash.zampto.net" in u and len(tx)>100:
            log(f"✅ 加载 ({len(tx)}c)"); return True
        if u and ("chrome://" in u): time.sleep(2); continue
        time.sleep(1)
    return False

def nav(sb, u, t=20):
    log(f"🌐 {u}")
    for _ in range(3):
        try: sb.open(u)
        except Exception as e: log(f"⚠️ {e}"); time.sleep(3); continue
        if wait_page(sb, t): return True
        log(f"⚠️ 失败 {url(sb)}"); shot(sb, "nav"); time.sleep(5)
    return False

def valid(sb):
    u=url(sb); tx=txt(sb).lower()
    if "chrome://" in u or len(tx)<50: return False
    if "just a moment" in tx or "checking" in tx:
        log("⚠️ CF..."); time.sleep(10); return valid(sb)
    if "1005" in tx: return False
    return True

def login(sb):
    if not (EMAIL and PASSWORD): return False
    if not nav(sb, f"{BASE_URL}/auth/login", 25): return False
    shot(sb,"login"); time.sleep(3)
    try: sb.find_element('input[name="email"], input[type="email"]', timeout=10); log("✅ 表单")
    except: log(f"⚠️ {txt(sb)[:200]}"); return False
    try:
        sb.type('input[name="email"], input[type="email"]', EMAIL, timeout=5)
        sb.type('input[name="password"], input[type="password"]', PASSWORD, timeout=5)
        log("✅ 输入完成")
    except Exception as e: log(f"⚠️ {e}"); return False
    time.sleep(2)
    try: sb.uc_gui_click_captcha(timeout=8); time.sleep(3)
    except: pass
    try: sb.click('button[type="submit"]', timeout=5)
    except:
        try: sb.execute_script("document.querySelector('form')?.submit()")
        except: pass
    time.sleep(5)
    u=url(sb); log(f"📌 {u}")
    if "login" in u.lower() or "auth" in u.lower(): log("❌ 登录失败"); return False
    log("✅ 登录"); return True

def do_renew(sb):
    u=f"{BASE_URL}/server?id={SERVER_ID}"
    if not nav(sb, u, 25): return False
    shot(sb,"server"); time.sleep(3)
    if not valid(sb): return False
    tx=txt(sb)
    try: log(f"📄 标题: {sb.get_page_title()}")
    except: pass
    log(f"📄 {tx[:300]}")
    
    btn=None
    for sel in ['button:contains("Renew")','button:contains("Extend")','button:contains("续期")']:
        try:
            es=sb.find_elements(sel)
            if es: btn=es[0]; log(f"✅ 按钮: '{(btn.text or '').strip()}'"); break
        except: continue
    if not btn:
        try:
            for b in sb.find_elements("button"):
                t=(b.text or "").strip()
                if t and ("renew" in t.lower() or "extend" in t.lower()): btn=b; log(f"✅ '{t}'"); break
        except: pass
    if not btn: log("❌ 未找到"); log(f"内容: {tx[:500]}"); return False
    
    log("🖱️ 点击...")
    try:
        sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(1)
        sb.execute_script("arguments[0].click()", btn)
        log("✅")
    except Exception as e:
        log(f"⚠️ {e}")
        try: btn.click()
        except: pass
    time.sleep(5)
    shot(sb,"clicked")
    
    tl=txt(sb).lower()
    if "security verification" in tl or "complete the security" in tl:
        log("🔐 弹窗...")
        try: sb.uc_gui_click_captcha(timeout=8); time.sleep(5)
        except: pass
    
    tx=txt(sb)
    for l in tx.split("\n"):
        if "last renewed" in l.lower() or "just renewed" in l.lower() or "renewed" in l.lower():
            log(f"📋 {l.strip()}")
    shot(sb,"result")
    return True

def main():
    log("="*40); log("Zampto 续期"); log("="*40)
    log(f"📌 服务器: {SERVER_ID}")
    if PROXY:
        try:
            r=requests.get("https://api.ipify.org", proxies={"http":PROXY,"https":PROXY}, timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except: log("⚠️ 代理不可用")
    
    # 清除系统代理环境变量
    for k in list(os.environ.keys()):
        if "proxy" in k.lower() or "PROXY" in k: os.environ.pop(k, None)
    
    log("🚀 启动浏览器...")
    try:
        with SB(uc=True, headless2=True, incognito=False) as sb:
            log("✅ 就绪"); time.sleep(2)
            if not nav(sb, BASE_URL, 25):
                log("❌ 首页"); send_tg("首页打不开","❌"); return
            time.sleep(3)
            u=url(sb); tx=txt(sb).lower()
            if ("login" in u.lower() or "auth" in u.lower()) and "server" not in tx:
                log("🔐 登录...")
                if not login(sb): send_tg("登录失败","❌"); return
            else: log("✅ 已登录")
            log("="*40)
            ok=do_renew(sb)
            if ok: log("🎉"); send_tg("续期操作完成","✅")
            else: log("❌"); send_tg("续期失败","❌")
    except Exception as e:
        log(f"💥 {e}"); send_tg(f"异常: {e}","💥")

if __name__=="__main__": main()