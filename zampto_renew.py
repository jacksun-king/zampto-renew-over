#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期 - v5
策略: 先用 requests + 代理登录拿 cookie，再注入浏览器续期
"""
import os, time, json, re
import requests
from seleniumbase import SB

EMAIL = os.environ.get("ZAMPTO_EMAIL", "")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("SERVER_ID", "13421")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("ALL_PROXY") or ""
BASE_URL = "https://dash.zampto.net"
_shot = 0

def log(m):
    ts=time.strftime("%H:%M:%S",time.gmtime(time.time()+28800))
    print(f"[{ts}] {m}",flush=True)

def shot(sb,t):
    global _shot;_shot+=1
    try:sb.save_screenshot(f"{_shot:02d}_{t}.png");log(f"📸{_shot:02d}_{t}")
    except:pass

def send_tg(m,i="ℹ️"):
    if not(TG_BOT_TOKEN and TG_CHAT_ID):return
    try:requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        json={"chat_id":TG_CHAT_ID,"text":f"{i} Zampto\n\n{m}"},timeout=15)
    except:pass

def proxy_dict():
    return {"http":PROXY,"https":PROXY} if PROXY else None

def innerText(sb):
    try:return sb.execute_script("return document.body.innerText||''")or""
    except:return""

def url(sb):
    try:return sb.get_current_url()
    except:return""

def api_login():
    """用 requests 登录获取 session cookie"""
    log("🔐 API 登录...")
    prox=proxy_dict()
    sess=requests.Session()
    if prox:sess.proxies=prox
    
    # 先访问首页获取可能的 CSRF token
    r=sess.get(BASE_URL,timeout=15)
    log(f"首页 HTTP {r.status_code}, cookies: {list(sess.cookies.keys())}")
    
    # 获取登录页
    r=sess.get(f"{BASE_URL}/auth/login",timeout=15)
    log(f"登录页 HTTP {r.status_code}")
    
    # 尝试 POST 登录
    login_data={"email":EMAIL,"password":PASSWORD}
    r=sess.post(f"{BASE_URL}/auth/login",data=login_data,timeout=15,allow_redirects=True)
    log(f"POST 登录 HTTP {r.status_code}, URL: {r.url}")
    
    cookies=sess.cookies.get_dict()
    log(f"Cookies: {list(cookies.keys())}")
    
    # 检查是否登录成功
    if "/auth/login" in r.url:
        log("⚠️ API 登录被拒，尝试其他端点...")
        # 尝试 /api/auth/login
        r2=sess.post(f"{BASE_URL}/api/auth/login",data=login_data,timeout=15)
        log(f"API 登录 HTTP {r2.status_code}")
        cookies=sess.cookies.get_dict()
    
    if "/auth/login" in r.url and "/auth/login" in r2.url:
        log("❌ API 登录失败")
        # 尝试 /api/v1/login
        r3=sess.post(f"{BASE_URL}/api/v1/login",json=login_data,timeout=15)
        log(f"API v1 HTTP {r3.status_code}")
        if r3.status_code==200:
            try:
                data=r3.json()
                log(f"响应: {json.dumps(data)[:200]}")
                cookies=sess.cookies.get_dict()
            except:pass
    
    has_session="zampto_session" in cookies
    log(f"zampto_session: {'✅' if has_session else '❌'}")
    return sess if has_session else None

def find_btn(sb):
    for sel in ['button:contains("Renew")','button:contains("Extend")']:
        try:
            es=sb.find_elements(sel)
            if es:
                for e in es:
                    t=(e.text or"").strip()
                    if t and("renew"in t.lower()or"extend"in t.lower()):
                        log(f"✅ 按钮: '{t}'");return e
        except:continue
    try:
        for b in sb.find_elements("button"):
            t=(b.text or"").strip()
            if t and("renew"in t.lower()or"extend"in t.lower()or"续期"in t):
                log(f"✅ 遍历: '{t}'");return b
    except:pass
    try:
        btn=sb.execute_script("""
            var els=document.querySelectorAll('button, a, div[role=button]');
            for(var e of els){var t=(e.innerText||e.textContent||'').trim().toLowerCase();
                if(t.includes('renew')||t.includes('extend')||t.includes('续期'))return e;}
            return null;
        """)
        if btn:log("✅ JS 找到");return btn
    except:pass
    return None

def wait_page(sb,t=20):
    st=time.time()
    while time.time()-st<t:
        u=url(sb);tx=innerText(sb)
        if u and "dash.zampto.net" in u and len(tx)>50:return True
        if u and "chrome://"in u:time.sleep(2);continue
        time.sleep(1)
    return False

def nav(sb,u,t=20):
    log(f"🌐 {u}")
    for _ in range(3):
        try:sb.open(u)
        except Exception as e:log(f"⚠️{e}");time.sleep(3);continue
        if wait_page(sb,t):return True
        log(f"⚠️{url(sb)}");shot(sb,"nav");time.sleep(5)
    return False

def main():
    log("="*40);log("Zampto 续期 v5");log("="*40)
    log(f"📌 服务器: {SERVER_ID}")
    if PROXY:
        try:
            r=requests.get("https://api.ipify.org",proxies=proxy_dict(),timeout=10)
            log(f"🌐 IP: {r.text.strip()}")
        except:log("⚠️ 代理不可用")
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():os.environ.pop(k,None)
    
    # Step 1: API 登录拿 cookie
    api_sess=api_login()
    if not api_sess:
        log("❌ API 登录失败，无法获取 cookie")
        send_tg("API 登录失败","❌")
        return
    
    api_cookies=api_sess.cookies.get_dict()
    log(f"✅ 获取到 {len(api_cookies)} 个 cookie")
    
    # Step 2: 启动浏览器，注入 cookie
    log("🚀 启动浏览器...")
    try:
        with SB(uc=True,headless2=True,incognito=False) as sb:
            log("✅ 就绪");time.sleep(2)
            
            # 注入 cookie 前先访问域名
            if not nav(sb,BASE_URL,25):
                log("❌ 首页打不开");send_tg("首页打不开","❌");return
            time.sleep(2)
            
            # 注入 cookie
            log("🍪 注入 cookie...")
            for name,value in api_cookies.items():
                try:
                    sb.add_cookie({"name":name,"value":value,"domain":".zampto.net","path":"/"})
                    log(f"  ✅ {name}")
                except Exception as e:
                    try:sb.add_cookie({"name":name,"value":value,"domain":"dash.zampto.net","path":"/"});log(f"  ✅ {name}(dash)")
                    except:log(f"  ⚠️ {name}: {e}")
            
            # 刷新页面让 cookie 生效
            sb.refresh()
            time.sleep(3)
            
            # 检查是否登录
            u=url(sb);tx=innerText(sb).lower()
            log(f"📌 {u} ({len(tx)}c)")
            if "login" in u.lower() or "auth" in u.lower():
                log("❌ cookie 注入后仍未登录")
                shot(sb,"not_logged");send_tg("登录失败","❌");return
            log("✅ 已登录")
            
            # Step 3: 续期
            u=f"{BASE_URL}/server?id={SERVER_ID}"
            if not nav(sb,u,25):return
            shot(sb,"server");time.sleep(5)
            tx=innerText(sb)
            try:log(f"📄 标题: {sb.get_page_title()}")
            except:pass
            log(f"📄 {tx[:400]}")
            
            btn=find_btn(sb)
            if not btn:
                log("❌ 未找到续期按钮")
                log(f"内容: {tx[:600]}")
                try:
                    src=sb.get_page_source()
                    with open("page.html","w") as f:f.write(src)
                except:pass
                return
            
            log("🖱️ 点击...")
            try:
                sb.execute_script("arguments[0].scrollIntoView({block:'center'});",btn)
                time.sleep(1)
                sb.execute_script("arguments[0].click()",btn)
                log("✅")
            except Exception as e:
                log(f"⚠️{e}")
                try:btn.click()
                except:pass
            time.sleep(5)
            shot(sb,"clicked")
            
            tl=innerText(sb).lower()
            if "security verification" in tl or "complete the security" in tl:
                log("🔐 弹窗...")
                try:sb.uc_gui_click_captcha(timeout=8);time.sleep(5)
                except:pass
            
            tx=innerText(sb)
            for l in tx.split("\n"):
                l=l.strip()
                if "last renewed" in l.lower()or"just renewed" in l.lower()or"renewed" in l.lower()or"expire" in l.lower():
                    log(f"📋 {l}")
            shot(sb,"result")
            log("🎉 完成");send_tg("续期完成","✅")
    except Exception as e:
        log(f"💥 {e}");send_tg(f"异常: {e}","💥")

if __name__=="__main__":main()